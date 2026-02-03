import warnings
from typing import Any, Final

import networkx as nx
import numpy as np
import pandas as pd


def create_st_traffic_graph(
    df: pd.DataFrame,
    dlon: float = 0.25,
    dlat: float = 0.25,
    dz: float | None = None,
    dt: float | None = None,
) -> nx.Graph:
    """Internal helper function for efficient graph construction using self-merge.

    Args:
        df (pd.DataFrame): Input DataFrame containing flight trajectory data.
        dlon (float, optional): longitude grid resolution (deg). Defaults to 0.25.
        dlat (float, optional): latitude grid resolution  (deg). Defaults to 0.25.
        dz (float, optional): altitude grid resolution (FL). Defaults to None.
        dt (float, optional): time grid resolution (s). Defaults to None.

    Returns:
        nx.Graph: Graph with edges representing shared spatiotemporal cells.
    """

    required_cols: Final[list[str]] = ["uid", "longitude", "latitude"]

    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"DataFrame missing required columns: {required_cols}")

    df_temp: pd.DataFrame = df.copy()
    df_temp.dropna(subset=required_cols, inplace=True)

    if df_temp.empty:
        return nx.Graph()

    grouping_cols: list[str] = []

    # Binning Logic
    df_temp.dropna(subset=required_cols, inplace=True)
    df_temp["ix"] = np.floor(df_temp["longitude"] / dlon).astype(np.int32)
    df_temp["iy"] = np.floor(df_temp["latitude"] / dlat).astype(np.int32)
    grouping_cols.extend(["ix", "iy"])

    if dz is not None and "altitude" in df_temp.columns:
        df_temp.dropna(subset=["altitude"], inplace=True)
        if not df_temp.empty:
            df_temp["iz"] = np.floor(df_temp["altitude"] / dz).astype(np.int32)
            grouping_cols.append("iz")

    if dt is not None and "time" in df_temp.columns:
        try:
            if not pd.api.types.is_datetime64_any_dtype(df_temp["time"]):
                df_temp["time"] = pd.to_datetime(df_temp["time"])
            time_numeric = df_temp["time"].astype(np.int64)
            dt_ns: int = int(dt * 1e9)

            temp_df = pd.DataFrame(
                {"time_numeric": time_numeric, "uid": df_temp["uid"]},
                index=df_temp.index,
            ).dropna()

            if not temp_df.empty:
                df_temp = df_temp.loc[temp_df.index].copy()
                df_temp["it"] = np.floor(temp_df["time_numeric"] / dt_ns).astype(np.int32)
                grouping_cols.append("it")
        except Exception:
            warnings.warn("Temporal dimension skipped due to error.", stacklevel=2)

    if len(grouping_cols) < 2:
        return nx.Graph()

    # Self-Merge for Edge Generation
    unique_cells = df_temp.groupby(["uid"] + grouping_cols).first().reset_index()
    edge_pairs = pd.merge(
        left=unique_cells,
        right=unique_cells,
        on=grouping_cols,
        suffixes=("_A", "_B"),
        how="inner",
    )
    edge_pairs = edge_pairs[edge_pairs["uid_A"] < edge_pairs["uid_B"]]

    if edge_pairs.empty:
        return nx.Graph()

    edge_weights_df: pd.DataFrame = (
        edge_pairs.groupby(["uid_A", "uid_B"]).size().reset_index(name="weight")
    )

    # Graph Construction
    G: nx.Graph = nx.Graph()  # noqa: N806  (networkx convention)
    G.add_nodes_from(df["uid"].unique())

    edge_list: list[tuple[Any, Any, dict[str, Any]]] = [
        (uid_a, uid_b, {"weight": weight})
        for uid_a, uid_b, weight in zip(
            edge_weights_df["uid_A"],
            edge_weights_df["uid_B"],
            edge_weights_df["weight"],
            strict=False,
        )
    ]
    G.add_edges_from(edge_list)
    return G


def cluster_st_traffic_louvain(
    list_of_df: list[pd.DataFrame],
    dlon: float = 0.25,
    dlat: float = 0.25,
    dz: float | None = None,
    dt: float | None = None,
    resolution: float = 1.0,
    min_community_size: int = 1,
) -> list[list[pd.DataFrame]]:
    """Cluster traffic trajectories using Louvain community detection.

    Args:
        df (pd.DataFrame): Input DataFrame containing flight trajectory data.
        dlon (float, optional): longitude grid resolution (deg). Defaults to 0.25.
        dlat (float, optional): latitude grid resolution  (deg). Defaults to 0.25.
        dz (float, optional): altitude grid resolution (FL). Defaults to None.
        dt (float, optional): time grid resolution (s). Defaults to None.
        min_community_size (int, optional): Minimum number of UIDs
            required for a community to remain separate. Smaller
            communities are merged. Defaults to 1 (no merging).

    Returns:
        List[List[pd.DataFrame]]: each sublist contains DataFrames
            belonging to the same cluster.
    """

    if not list_of_df:
        return []

    uid_attr_cols: Final[list[str]] = [
        "departure_airport",
        "arrival_airport",
        "flight_id",
        "aobt",
    ]
    traj_cols: Final[list[str]] = ["latitude", "longitude", "time", "altitude"]

    data_for_concat: list[pd.DataFrame] = []

    # Map UID -> original list index (i).
    uid_to_original_idx: dict[Any, int] = {}

    # 1. Trajectory Data Preparation and Central Mapping (O(N) single pass)
    for i, df_segment in enumerate(list_of_df):
        # --- Metadata Validation and UID Creation ---
        missing_attrs = [col for col in uid_attr_cols if col not in df_segment.attrs]

        if missing_attrs:
            raise KeyError(
                f"DataFrame at index {i} is missing required attributes: {missing_attrs}"
            )

        # Create the unique UID string
        uid_parts = [str(df_segment.attrs[col]) for col in uid_attr_cols]
        uid_val = "_".join(uid_parts)

        # Store the mapping once
        uid_to_original_idx[uid_val] = i

        # --- Trajectory Data Preparation ---
        # Concatenated DF needs ONLY trajectory data and the UID.
        temp_df = df_segment[traj_cols].copy()
        temp_df["uid"] = uid_val

        data_for_concat.append(temp_df)

    # 2. Concatenate and Compute Graph
    full_df: pd.DataFrame = pd.concat(data_for_concat, ignore_index=True)
    G: nx.Graph = create_st_traffic_graph(full_df, dlon, dlat, dz, dt)  # noqa: N806

    if not G.nodes:
        warnings.warn(
            "Graph has no nodes/edges after processing. Returning unclustered data.",
            stacklevel=2,
        )
        return [list_of_df]

    # 3. Cluster using Louvain Community Detection
    try:
        partition: list[set[Any]] = nx.community.louvain_communities(
            G,
            weight="weight",
            resolution=resolution,
        )
    except Exception as e:
        warnings.warn(f"Louvain failed: {e}. Returning unclustered data.", stacklevel=2)
        return [list_of_df]

    # --- 3.5. Post-Processing: Filter and Merge Small Communities ---
    major_communities: list[set[Any]] = []
    minor_community_uids: set[Any] = set()

    for community_set in partition:
        if len(community_set) >= min_community_size:
            major_communities.append(community_set)
        else:
            minor_community_uids.update(community_set)

    if minor_community_uids:
        major_communities.append(minor_community_uids)
        warnings.warn(
            f"Merged {len(partition) - len(major_communities)} communities "
            f"(size < {min_community_size}) into a single Minor/Noise cluster "
            f"({len(minor_community_uids)} UIDs).",
            stacklevel=2,
        )

    final_partition = major_communities

    # 4. Segment and Reconstruct DataFrames (Partition-Driven)

    clustered_data: list[list[pd.DataFrame]] = []

    for community_set in final_partition:
        # Store the DataFrames belonging to the current community
        cluster_list_of_df: list[pd.DataFrame] = []

        for uid in community_set:
            original_idx = uid_to_original_idx[uid]
            cluster_list_of_df.append(list_of_df[original_idx])

        clustered_data.append(cluster_list_of_df)

    return clustered_data


class LouvainTrafficClusterer:
    """
    Implementation of the ClusteringProtocol using the highly optimized
    spatiotemporal graph-based Louvain method.
    """

    def __init__(
        self,
        dlon: float = 0.25,
        dlat: float = 0.25,
        dz: float | None = None,
        dt: float | None = None,
        resolution: float = 1.0,
        min_community_size: int = 1,
    ):
        """Initializes the clusterer with configuration parameters."""
        self.dlon = dlon
        self.dlat = dlat
        self.dz = dz
        self.dt = dt
        self.resolution = resolution
        self.min_community_size = min_community_size

    def __call__(
        self,
        list_of_df: list[pd.DataFrame],
        **kwargs: Any,  # Accepts arbitrary kwargs for flexibility
    ) -> list[list[pd.DataFrame]]:
        """Executes the clustering process, conforming to the Protocol."""

        # Merge instance attributes with any passed kwargs, giving priority to kwargs
        config = {
            "dlon": kwargs.get("dlon", self.dlon),
            "dlat": kwargs.get("dlat", self.dlat),
            "dz": kwargs.get("dz", self.dz),
            "dt": kwargs.get("dt", self.dt),
            "resolution": kwargs.get("resolution", self.resolution),
            "min_community_size": kwargs.get("min_community_size", self.min_community_size),
        }

        # Call the core logic (your highly efficient function)
        return cluster_st_traffic_louvain(
            list_of_df,
            dlon=config["dlon"],
            dlat=config["dlat"],
            dz=config["dz"],
            dt=config["dt"],
            resolution=config["resolution"],
            min_community_size=config["min_community_size"],
        )
