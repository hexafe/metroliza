"""Matplotlib violin rendering without one-dimensional BLAS dispatch overhead."""

from __future__ import annotations

import numpy as np


def _univariate_density(values, coords):
    """Evaluate Matplotlib's full KDE with identical point and reduction order.

    The inverse covariance is a 1x1 matrix. Its dot product is just scalar
    multiplication; avoiding BLAS here avoids dispatching a thread pool for
    every density coordinate. No observations or density coordinates are lost.
    """
    from matplotlib.mlab import GaussianKDE

    if np.all(values[0] == values):
        return (values[0] == coords).astype(float)
    kde = GaussianKDE(values)
    points = np.atleast_2d(coords)
    result = np.zeros(points.shape[1])
    inverse_covariance = kde.inv_cov[0, 0]
    if points.shape[1] >= kde.num_dp:
        for index in range(kde.num_dp):
            diff = kde.dataset[:, index, np.newaxis] - points
            energy = np.sum(diff * (inverse_covariance * diff), axis=0) / 2.0
            result = result + np.exp(-energy)
    else:
        for index in range(points.shape[1]):
            diff = kde.dataset - points[:, index, np.newaxis]
            energy = np.sum(diff * (inverse_covariance * diff), axis=0) / 2.0
            result[index] = np.sum(np.exp(-energy), axis=0)
    return result / kde.norm_factor


def full_data_violin(ax, dataset, **kwargs):
    """Draw the default 100-coordinate Scott KDE using every finite observation."""
    from matplotlib.cbook import violin_stats

    return ax.violin(violin_stats(dataset, _univariate_density), **kwargs)
