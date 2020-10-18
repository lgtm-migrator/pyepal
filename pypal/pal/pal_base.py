# -*- coding: utf-8 -*-
"""Base class for PAL"""

from typing import List, Union

import numpy as np

from .core import _get_max_wt, _get_uncertainty_regions, _pareto_classify, _union
from .validate_inputs import (
    base_validate_models,
    validate_beta_scale,
    validate_delta,
    validate_epsilon,
    validate_goals,
    validate_ndim,
)


class PALBase:  # pylint:disable=too-many-instance-attributes
    """PAL base class"""

    def __init__(  # pylint:disable=too-many-arguments
        self,
        X_design: np.array,
        models: list,
        ndim: int,
        epsilon: Union[list, float] = 0.01,
        delta: float = 0.05,
        beta_scale: float = 1 / 9,
        goals: List[str] = None,
    ):
        """Initialize the PAL instance

        Args:
            X_design (np.array): Design space (feature matrix)
            models (list): Machine learning models
            ndim (int): Number of objectives
            epsilon (Union[list, float], optional): Epsilon hyperparameter.
                Defaults to 0.01.
            delta (float, optional): Delta hyperparameter. Defaults to 0.05.
            beta_scale (float, optional): Scaling parameter for beta.
                If not equal to 1, the theoretical guarantees do not necessarily hold.
                Also note that the parametrization depends on the kernel type.
                Defaults to 1/9.
            goals (List[str], optional): If a list, provide "min" for every objective
                that shall be minimized and "max" for every objective
                that shall be maximized. Defaults to None, which means
                that the code maximizes all objectives.
        """
        self.ndim = validate_ndim(ndim)
        self.epsilon = validate_epsilon(epsilon, self.ndim)
        self.delta = validate_delta(delta)
        self.beta_scale = validate_beta_scale(beta_scale)
        self.pareto_optimal = np.array([False] * len(X_design))
        self.discarded = np.array([False] * len(X_design))
        self.sampled = np.array([[False] * self.ndim] * len(X_design))
        self.unclassified = np.array([True] * len(X_design))
        self.rectangle_ups: np.array = None
        self.rectangle_lows: np.array = None
        self.models = base_validate_models(models)
        self.iteration = 1
        self.design_space_size = len(X_design)
        # means/std are the model predictions
        self.means: np.array = None
        self.std: np.array = None

        self.design_space = X_design
        self.beta = None
        self.goals = validate_goals(goals, ndim)
        self.sampled_idx = np.array([0])
        # self.y is what needs to be used for train/predict
        # as there the data has been turned into maximization
        # self._y contains the data as provided by the user
        self.y = np.zeros(  # pylint:disable=invalid-name
            (self.design_space_size, self.ndim)
        )
        self._y = self.y
        # measurement_uncertainity is provided in update_train_set by the user
        self.measurement_uncertainty = np.zeros((self.design_space_size, self.ndim))
        self._has_train_set = False

    def __repr__(self):
        return f"pypal at iteration {self.iteration}. \
        {self.number_pareto_optimal_points} Pareto optimal points, \
        {self.number_discarded_points} discarded points, \
        {self.number_unclassified_points} unclassified points."

    @property
    def pareto_optimal_points(self):
        """Return the pareto optimal points"""
        return self.design_space[self.pareto_optimal]

    @property
    def sampled_points(self):
        """Return the sampled points"""
        return self.design_space[self.sampled_indices]

    @property
    def discarded_points(self):
        """Return the discarded points"""
        return self.design_space[self.discarded]

    @property
    def unclassified_points(self):
        """Return the discarded points"""
        return self.design_space[self.unclassified]

    @property
    def pareto_optimal_indices(self):
        """Return the indices of the Pareto optimal points"""
        return np.where(self.pareto_optimal)[0]

    @property
    def sampled_indices(self):
        """Return the indices of the sampled points"""
        return np.unique(np.where(self.sampled)[0])

    @property
    def discarded_indices(self):
        """Return the indices of the discarded points"""
        return np.where(self.discarded)[0]

    @property
    def unclassified_indices(self):
        """Return the indices of the unclassified points"""
        return np.where(self.unclassified)[0]

    @property
    def number_pareto_optimal_points(self):
        """Return the number of Pareto optimal points"""
        return sum(self.pareto_optimal)

    @property
    def number_discarded_points(self):
        """Return the nnumber of discarded points"""
        return sum(self.discarded)

    @property
    def number_unclassified_points(self):
        """Return the number of unclassified points"""
        return sum(self.unclassified)

    @property
    def number_sampled_points(self):
        """Return the number of sampled points"""
        return len(self.sampled_indices)

    def _update_beta(self):
        """Update beta according to section 7.2. of the epsilon-PAL paper"""
        self.beta = (
            self.beta_scale
            * 2
            * np.log(
                self.ndim
                * self.design_space_size
                * np.square(np.pi)
                * np.square(self.iteration + 1)
                / (6 * self.delta)
            )
        )

    def _log(self):
        pass

    def _should_optimize_hyperparameters(self) -> bool:  # pylint:disable=no-self-use
        return True

    def _predict(self):
        raise NotImplementedError("The predict function is not implemented")

    def _set_hyperparameters(self):
        pass

    def _turn_to_maximization(self):
        self.y = self._y * self.goals

    def _train(self):
        pass

    def _set_data(self):
        pass

    def _update_hyperrectangles(self):
        """Computes new hyperrectangles based on beta,
        the means and the standard deviations.
        If the iteration is > 0,
        then it uses iterative intersection to ensure that the size of the
        hyperrectangles is decreasing.
        """
        lows, ups = _get_uncertainty_regions(self.means, self.std, np.sqrt(self.beta))
        if self.iteration == 1:
            # initialization
            self.rectangle_lows, self.rectangle_ups = lows, ups
        else:
            self.rectangle_lows, self.rectangle_ups = _union(
                self.rectangle_lows, self.rectangle_ups, lows, ups
            )

    def _classify(self):
        self.pareto_optimal, self.discarded, self.unclassified = _pareto_classify(
            self.pareto_optimal,
            self.discarded,
            self.unclassified,
            self.rectangle_lows,
            self.rectangle_ups,
            self.epsilon,
        )

    def _replace_by_measurements(self):
        """Implements one "trick". Instead of using the GPR
        predictions for the sampled points we use the data that
        was actually measured and the actual uncertainty.
        This is different from the PAL implementation proposed
        by Zuluaga et al. This could make issues when the measurements
        are outliers"""
        self.means[self.sampled] = self.y[self.sampled]
        self.std[self.sampled] = self.measurement_uncertainty[self.sampled]

    def run_one_step(self, batch_size: int = 1) -> Union[np.array, None]:
        """[summary]

        Args:
            batch_size (int, optional): Number of indices that will be returned.
                Defaults to 1.

        Raises:
            ValueError: In case the PAL instance was not initialized with
                measurements.

        Returns:
            Union[np.array, None]: Returns array of indices if there are
                unclassified points that can be sample left.
        """
        if not self._has_train_set:
            raise ValueError(
                "You need to provide a set of points to train the model on.\
               Before the first iteration, call the update_train_set() function."
            )
        self._set_data()
        if self._should_optimize_hyperparameters():
            self._set_hyperparameters()
        self._train()
        self._predict()
        self._update_beta()
        self._replace_by_measurements()
        self._update_hyperrectangles()
        self._classify()
        samples = np.array([], dtype=np.int)
        if sum(self.unclassified):
            for _ in range(batch_size):
                sampled_idx = self.sample(exclude_idx=samples)
                samples = np.append(samples, [sampled_idx])
                self._log()

            self.sampled_idx = samples
            self._log()
            self.iteration += 1

            return samples
        print("Done. No unclassified point left")
        return None

    def update_train_set(
        self,
        indices: np.ndarray,
        measurements: np.ndarray,
        measurement_uncertainty: np.ndarray = None,
    ):
        """Update training set following a measurement

        Args:
            indices (np.ndarray): Indices of design space at which
                the measurements were taken
            measurements (np.ndarray): Measured values, 2D array.
                the length must equal the length of the indices array.
                the second direction must equal the number of objectives.
                If an objective is missing, provide np.nan. For example,
                np.array([1, 1, np.nan])
            measurement_uncertainty (np.ndarray): uncertainty in the measuremens,
                if not provided (None) will be zero. If it is not None, it must be
                an array with the same shape as the measurements
                If an objective is missing, provide np.nan.
                For example, np.array([1, 1, np.nan])
        """
        self._has_train_set = True
        assert measurements.shape[1] == self.ndim
        assert len(indices) == len(measurements)
        if measurement_uncertainty is not None:
            assert measurement_uncertainty.shape == measurements.shape
        else:
            measurement_uncertainty = np.zeros(measurements.shape)
        self._y[indices] = measurements
        self.measurement_uncertainty[indices] = measurement_uncertainty
        # This sets "sampled" to False for the objectives that have not been measured
        self.sampled[indices] = ~np.isnan(measurements)
        self._turn_to_maximization()

    def sample(self, exclude_idx: Union[np.array, None] = None) -> int:
        """Runs the sampling step based on the size of the hyperrectangle.
        I.e., favoring exploration.

        Args:
            exclude_idx (Union[np.array, None], optional):
                Points in design space to exclude from sampling.
                Defaults to None.

        Raises:
            ValueError: In case there are no uncertainty rectangles,
                i.e., when the _predict has not been successfully called.

        Returns:
            int: Index of next point to evaluate in design space
        """
        if (self.rectangle_lows is None) | (self.rectangle_ups is None):
            raise ValueError(
                "You need to have uncertainty rectangles\
                     before you can peform the sampling"
            )

        # We count a point as sampled if at least one objective has
        # been measured, i.e., self.sampled is a N * number objectives
        # array in which some columns can be false if a measurement
        # has not been performed
        sampled_mask = self.sampled.sum(axis=1) > 0

        # This is to handle the case of batch sampling, where we do need
        # to make sure that we do not sample the same points
        if isinstance(exclude_idx, np.ndarray):
            if len(exclude_idx) >= 1:
                exclude_mask = np.zeros(len(sampled_mask), dtype=bool)
                exclude_mask[exclude_idx] = True

                sampled_mask += exclude_mask

        sampled_idx = _get_max_wt(
            self.rectangle_lows,
            self.rectangle_ups,
            self.means,
            self.pareto_optimal,
            self.unclassified,
            sampled_mask,
        )

        return sampled_idx
