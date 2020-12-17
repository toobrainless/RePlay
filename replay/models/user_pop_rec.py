"""
Библиотека рекомендательных систем Лаборатории по искусственному интеллекту.
"""
from typing import Optional

import numpy as np
import pandas as pd
from pyspark.sql import DataFrame
from pyspark.sql import functions as sf
from pyspark.sql import types as st

from replay.models.base_rec import Recommender


class UserPopRec(Recommender):
    """
    Рекомендатель на основе популярности объектов для каждого
    пользователя. ВАЖНО! Может рекомендовать только те объекты, которые
    пользователь уже видел.

    Популярность объекта для выбранного пользователя определяется как отношение
    количества взаимодействий между данным объектом и выбранным пользователем к
    общему количеству взимодействий данного пользователя:

    .. math::
        Popularity(i_u) = \\dfrac{N_iu}{N_u}

    :math:`N_iu` - количество взаимодействий пользователя :math:`u` с
    объектом :math:`i`.
    :math:`N_u` - общее количество взаимодействий пользователя :math:`u`.

    >>> import pandas as pd
    >>> data_frame = pd.DataFrame({"user_id": [1, 1, 3], "item_id": [1, 2, 3], "relevance": [2, 1, 1]})
    >>> data_frame
       user_id  item_id  relevance
    0        1        1          2
    1        1        2          1
    2        3        3          1

    >>> res = UserPopRec().fit_predict(data_frame, 1)
    >>> res.count() == 0
    True

    >>> res = UserPopRec().fit_predict(data_frame, 1, filter_seen_items=False)
    >>> res.toPandas().sort_values("user_id", ignore_index=True)
       user_id  item_id  relevance
    0        1        1   0.666667
    1        3        3   1.000000
    """

    item_popularity: DataFrame

    def _fit(
        self,
        log: DataFrame,
        user_features: Optional[DataFrame] = None,
        item_features: Optional[DataFrame] = None,
    ) -> None:
        user_item_count = (
            log.groupBy("user_idx")
            .agg(sf.sum("relevance").alias("item_count"))
            .withColumnRenamed("user_idx", "user")
            .select("user", "item_count")
        )
        self.item_popularity = (
            log.groupBy("user_idx", "item_idx")
            .agg(sf.sum("relevance").alias("user_count"))
            .join(
                user_item_count,
                how="inner",
                on=sf.col("user_idx") == sf.col("user"),
            )
            .select(
                "user_idx",
                "item_idx",
                (sf.col("user_count") / sf.col("item_count")).alias(
                    "relevance"
                ),
            )
        ).cache()

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
        # удаляем ненужные items
        if filter_seen_items:
            self.logger.warning(
                "Для рекомендателя UserPopRec параметр "
                "filter_seen_items должен иметь значение False"
                " иначе результат будет пустым."
            )

        item_popularity_by_user = items.join(
            self.item_popularity.withColumnRenamed("item_idx", "item"),
            on=sf.col("item_idx") == sf.col("item"),
            how="inner",
        ).drop("item")

        @sf.pandas_udf(
            st.StructType(
                [
                    st.StructField("user_idx", st.IntegerType(), True),
                    st.StructField("item_idx", st.IntegerType(), True),
                    st.StructField("relevance", st.DoubleType(), True),
                ]
            ),
            sf.PandasUDFType.GROUPED_MAP,
        )
        def grouped_map(pandas_df):
            user_idx = pandas_df["user_idx"][0]
            items_idx = np.argsort(pandas_df["relevance"].values)[-k:]

            return pd.DataFrame(
                {
                    "user_idx": k * [user_idx],
                    "item_idx": pandas_df["item_idx"].values[items_idx],
                    "relevance": pandas_df["relevance"].values[items_idx],
                }
            )

        recs = (
            users.join(log, how="left", on="user_idx")
            .select("user_idx", "item_idx")
            .groupby("user_idx")
            .agg(sf.countDistinct("item_idx").alias("cnt"))
            .join(
                item_popularity_by_user.withColumnRenamed("user_idx", "user"),
                on=sf.col("user_idx") == sf.col("user"),
                how="inner",
            )
            .drop("user")
        )
        recs = (
            recs.select("user_idx", "item_idx", "relevance")
            .groupby("user_idx")
            .apply(grouped_map)
        )

        return recs
