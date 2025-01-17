# pylint: disable=too-many-lines
"""
NeighbourRec - base class that requires log at prediction time.
Part of set of abstract classes (from base_rec.py)
"""

from abc import ABC
from typing import (
    Any,
    Dict,
    Iterable,
    Optional,
    Union,
)

from pyspark.sql import DataFrame
from pyspark.sql import functions as sf
from pyspark.sql.column import Column

from replay.models.extensions.ann.ann_mixin import ANNMixin
from replay.models.base_rec import Recommender


class NeighbourRec(Recommender, ANNMixin, ABC):
    """Base class that requires log at prediction time"""

    similarity: Optional[DataFrame]
    can_predict_item_to_item: bool = True
    can_predict_cold_users: bool = True
    can_change_metric: bool = False
    item_to_item_metrics = ["similarity"]
    _similarity_metric = "similarity"

    @property
    def _dataframes(self):
        return {"similarity": self.similarity}

    def _clear_cache(self):
        if hasattr(self, "similarity"):
            self.similarity.unpersist()

    # pylint: disable=missing-function-docstring
    @property
    def similarity_metric(self):
        return self._similarity_metric

    @similarity_metric.setter
    def similarity_metric(self, value):
        if not self.can_change_metric:
            raise ValueError(
                "This class does not support changing similarity metrics"
            )
        if value not in self.item_to_item_metrics:
            raise ValueError(
                f"Select one of the valid metrics for predict: "
                f"{self.item_to_item_metrics}"
            )
        self._similarity_metric = value

    def _predict_pairs_inner(
        self,
        log: DataFrame,
        filter_df: DataFrame,
        condition: Column,
        users: DataFrame,
    ) -> DataFrame:
        """
        Get recommendations for all provided users
        and filter results with ``filter_df`` by ``condition``.
        It allows to implement both ``predict_pairs`` and usual ``predict``@k.

        :param log: historical interactions, DataFrame
            ``[user_idx, item_idx, timestamp, relevance]``.
        :param filter_df: DataFrame use to filter items:
            ``[item_idx_filter]`` or ``[user_idx_filter, item_idx_filter]``.
        :param condition: condition used for inner join with ``filter_df``
        :param users: users to calculate recommendations for
        :return: DataFrame ``[user_idx, item_idx, relevance]``
        """
        if log is None:
            raise ValueError(
                "log is not provided, but it is required for prediction"
            )

        recs = (
            log.join(users, how="inner", on="user_idx")
            .join(
                self.similarity,
                how="inner",
                on=sf.col("item_idx") == sf.col("item_idx_one"),
            )
            .join(
                filter_df,
                how="inner",
                on=condition,
            )
            .groupby("user_idx", "item_idx_two")
            .agg(sf.sum(self.similarity_metric).alias("relevance"))
            .withColumnRenamed("item_idx_two", "item_idx")
        )
        return recs

    # pylint: disable=too-many-arguments
    def _predict(
        self,
        log: DataFrame,
        k: int,
        users: DataFrame,
        items: DataFrame,
        user_features: Optional[DataFrame] = None,
        item_features: Optional[DataFrame] = None,
        filter_seen_items: bool = True,
    ) -> DataFrame:

        return self._predict_pairs_inner(
            log=log,
            filter_df=items.withColumnRenamed("item_idx", "item_idx_filter"),
            condition=sf.col("item_idx_two") == sf.col("item_idx_filter"),
            users=users,
        )

    def _predict_pairs(
        self,
        pairs: DataFrame,
        log: Optional[DataFrame] = None,
        user_features: Optional[DataFrame] = None,
        item_features: Optional[DataFrame] = None,
    ) -> DataFrame:

        if log is None:
            raise ValueError(
                "log is not provided, but it is required for prediction"
            )

        return self._predict_pairs_inner(
            log=log,
            filter_df=(
                pairs.withColumnRenamed(
                    "user_idx", "user_idx_filter"
                ).withColumnRenamed("item_idx", "item_idx_filter")
            ),
            condition=(sf.col("user_idx") == sf.col("user_idx_filter"))
            & (sf.col("item_idx_two") == sf.col("item_idx_filter")),
            users=pairs.select("user_idx").distinct(),
        )

    def get_nearest_items(
        self,
        items: Union[DataFrame, Iterable],
        k: int,
        metric: Optional[str] = None,
        candidates: Optional[Union[DataFrame, Iterable]] = None,
    ) -> DataFrame:
        """
        Get k most similar items be the `metric` for each of the `items`.

        :param items: spark dataframe or list of item ids to find neighbors
        :param k: number of neighbors
        :param metric: metric is not used to find neighbours in NeighbourRec,
            the parameter is ignored
        :param candidates: spark dataframe or list of items
            to consider as similar, e.g. popular/new items. If None,
            all items presented during model training are used.
        :return: dataframe with the most similar items an distance,
            where bigger value means greater similarity.
            spark-dataframe with columns ``[item_idx, neighbour_item_idx, similarity]``
        """

        if metric is not None:
            self.logger.debug(
                "Metric is not used to determine nearest items in %s model",
                str(self),
            )

        return self._get_nearest_items_wrap(
            items=items,
            k=k,
            metric=metric,
            candidates=candidates,
        )

    def _get_nearest_items(
        self,
        items: DataFrame,
        metric: Optional[str] = None,
        candidates: Optional[DataFrame] = None,
    ) -> DataFrame:

        similarity_filtered = self.similarity.join(
            items.withColumnRenamed("item_idx", "item_idx_one"),
            on="item_idx_one",
        )

        if candidates is not None:
            similarity_filtered = similarity_filtered.join(
                candidates.withColumnRenamed("item_idx", "item_idx_two"),
                on="item_idx_two",
            )

        return similarity_filtered.select(
            "item_idx_one",
            "item_idx_two",
            "similarity" if metric is None else metric,
        )

    def _get_ann_build_params(self, log: DataFrame) -> Dict[str, Any]:
        self.index_builder.index_params.items_count = log.select(sf.max("item_idx")).first()[0] + 1
        return {
            "features_col": None,
        }

    def _get_vectors_to_build_ann(self, log: DataFrame) -> DataFrame:
        similarity_df = self.similarity.select(
            "similarity", "item_idx_one", "item_idx_two"
        )
        return similarity_df

    def _get_vectors_to_infer_ann_inner(
            self, log: DataFrame, users: DataFrame
    ) -> DataFrame:

        user_vectors = (
            log.groupBy("user_idx").agg(
                sf.collect_list("item_idx").alias("vector_items"),
                sf.collect_list("relevance").alias("vector_relevances"))
        )
        return user_vectors
