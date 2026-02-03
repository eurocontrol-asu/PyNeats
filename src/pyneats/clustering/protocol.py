from typing import Any, Protocol

import pandas as pd


class ClusteringProtocol(Protocol):
    """
    A Protocol defining the required interface for any traffic clustering
    implementation.

    Any class or function that implements this protocol must accept a list of
    pandas DataFrames (trajectories) and return a list of lists of pandas
    DataFrames (clusters).
    """

    def __call__(
        self,
        list_of_df: list[pd.DataFrame],
        # Optional parameters for resolution, binning, etc., can be added here
        # to ensure all implementations support the same configuration arguments.
        **kwargs: Any,
    ) -> list[list[pd.DataFrame]]:
        """
        The main method to execute the clustering logic.

        Args:
            list_of_df: A list of input DataFrames, where each DataFrame
                        represents a single flight trajectory.
            **kwargs: Configuration parameters (e.g., dlon, dt, resolution).

        Returns:
            A list where each inner list contains the DataFrames (trajectories)
            that belong to a single cluster.
        """
        ...
