# pylint: skip-file
import copy
from collections.abc import Iterable
from typing import Dict, Optional, Tuple, List, Union, Callable, Any

import pyspark.sql.functions as sf
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.sql import DataFrame
from pyspark.sql.functions import col, isnull, lit, when

from lightautoml.automl.presets.tabular_presets import TabularAutoML

# from lightautoml.dataset.roles import DatetimeRole, TextRole
from lightautoml.tasks import Task

# from lightautoml.utils.profiler import Profiler

from replay.constants import AnyDataFrame
from replay.experiment import Experiment
from replay.filters import min_entries

from replay.metrics import HitRate, Metric, NDCG
from replay.models import ALSWrap, RandomRec
from replay.models.base_rec import Recommender

# from replay.models.classifier_rec import ClassifierRec
from replay.scenarios.basescenario import BaseScenario
from replay.session_handler import State
from replay.splitters import Splitter, UserSplitter
from replay.utils import (
    get_log_info,
    horizontal_explode,
    join_or_return,
    convert2spark,
)


# pylint: disable=too-many-instance-attributes
class TwoStagesScenario(BaseScenario):
    """
    Двухуровневый сценарий состоит из следующих этапов:
    train:
    * получить ``log`` взаимодействия и разбить его на first_level_train и second_level_train
    с помощью переданного splitter-а или дефолтного splitter, разбивающего лог для каждого пользователя 50/50
    * на ``first_stage_train`` обучить ``first_stage_models`` - модели первого уровня, которые могут предсказывать
    релевантность и генерировать дополнительные признаки пользователей и объектов (эмбеддинги)
    * сгенерировать негативные примеры для обучения модели второго уровня
        - как предсказания основной модели первого уровня, не релевантные для пользователя
        - случайным образом
    количество негативных примеров на 1 пользователя определяется параметром ``num_negatives``
    * дополнить датасет признаками:
        - получить предсказания моделей 1 уровня для позитивных взаимодействий из second_level_train и сгенерированных
    негативных примеров
        - дополнить полученный датасет признаками пользователей и объектов,
        - сгенерировать признаки взаимодействия для пар пользователь-айтем и статистические признаки
    * обучить ``TabularAutoML`` из библиотеки LightAutoML на полученном датасете с признаками

    inference:
    * получить ``log`` взаимодействия
    * сгенерировать объекты-кандидаты с помощью модели первого уровня для оценки моделью второго уровня
    количество кандидатов по дефолту равно числу негативных примеров при обучении и определяется параметром
     ``num_candidates``
    * дополнить полученный датасет признаками аналогично дополнению в train
    * получить top-k взаимодействий для каждого пользователя
    """

    can_predict_cold_users: bool = True
    can_predict_cold_items: bool = True

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        train_splitter: Splitter = UserSplitter(
            item_test_size=0.5, shuffle=True, seed=42
        ),
        first_level_models: Union[List[Recommender], Recommender] = ALSWrap(
            rank=128
        ),
        use_first_level_features: Union[List[bool], bool] = False,
        second_model_params: Optional[Union[Dict, str]] = None,
        second_model_config_path: Optional[str] = None,
        num_negatives: int = 100,
        negatives_type: str = "first_level",
        use_generated_features: bool = False,
        user_cat_features_list: Optional[List] = None,
        item_cat_features_list: Optional[List] = None,
        custom_features_processor: Callable = None,
        seed: int = 123,
    ) -> None:
        """
        Сборка двухуровневой рекомендательной архитектуры из блоков

        :param train_splitter: splitter для разбиения лога на ``first_level_train`` и ``second_level_train``.
            По умолчанию для каждого пользователя 50% объектов из лога, выбранные случайно (не по времени),
            используются для обучения модели первого уровня (first_level_train),
            а остальное - для обучения модели второго уровня (second_level_train).
        :param first_level_models: Модель или список инициализированных моделей RePlay, использующихся
            на первом этапе обучения. Для генерации кандидатов для переранжирования моделью второго уровня
            используется первая модель из списка. По умолчанию используется модель :ref:`ALS<als-rec>`.
        :param use_first_level_features: Флаг или список флагов, определяющих использование признаков,
            полученных моделью первого уровня (например, вектора пользователей и объектов из ALS,
            эмбеддинги пользователей из multVAE), для обучения модели второго уровня.
            Если bool, флаг применяется ко всем моделям, в случае передачи списка
            для каждой модели должно быть указано свое значение флага.
        :param second_model_params: Параметры TabularAutoML в виде многоуровневого dict
        :param second_model_config_path: Путь к конфиг-файлу для настройки TabularAutoML
        :param num_negatives: сколько объектов класса 0 будем генерировать для обучения
        :param negatives_type: каким образом генерировать негативные примеры для обучения модели второго уровня,
            случайно ``random`` или как наиболее релевантные предсказанные моделью первого уровня ``first-level``
        :param use_generated_features: нужно ли использовать автоматически сгенерированные
            по логу признаки для обучения модели второго уровня
        :param user_cat_features_list: категориальные признаки пользователей, которые нужно использовать для построения признаков
            популярности объекта у пользователей в зависимости от значения категориального признака
            (например, популярность фильма у пользователей данной возрастной группы)
        :param item_cat_features_list: категориальные признаки объектов, которые нужно использовать для построения признаков
            популярности у пользователя объектов в зависимости от значения категориального признака
        :param custom_features_processor: в двухуровневый сценарий можно передать свой callable-объект для
            генерации признаков для выбранных пар пользователь-объект во время обучения и inference
            на базе лога и признаков пользователей и объектов.
            Пример реализации - TwoLevelFeaturesProcessor.
        :param seed: random seed для обеспечения воспроизводимости результатов.
        """

        # разбиение данных
        super().__init__(cold_model=None, threshold=0)
        self.train_splitter = train_splitter

        # модели первого уровня
        self.first_level_models = (
            first_level_models
            if isinstance(first_level_models, Iterable)
            else [first_level_models]
        )

        self.random_model = RandomRec(seed=seed)

        if isinstance(use_first_level_features, bool):
            self.use_first_level_models_feat = [
                use_first_level_features
            ] * len(self.first_level_models)
        else:
            if len(self.first_level_models) != len(use_first_level_features):
                raise ValueError(
                    "Для каждой модели из first_level_models укажите,"
                    "нужно ли использовать фичи, полученные моделью. Длина списков не совпадает."
                    "Количество моделей (first_level_models) равно {}, "
                    "количество флагов использования признаков (use_first_level_features) равно {}".format(
                        len(first_level_models), len(use_first_level_features)
                    )
                )

            self.use_first_level_models_feat = use_first_level_features

        # модель второго уровня
        if (
            second_model_config_path is not None
            or second_model_params is not None
        ):
            second_model_params = (
                dict() if second_model_params is None else second_model_params
            )
            self.second_stage_model = TabularAutoML(
                config_path=second_model_config_path, **second_model_params
            )
        else:
            self.second_stage_model = TabularAutoML(
                task=Task("binary"),
                reader_params={"cv": 5, "random_state": seed},
            )

        # генерация отрицательных примеров
        self.num_negatives = num_negatives
        if negatives_type not in ["random", "first_level"]:
            raise ValueError(
                "incorrect negatives_type, select random or first_level"
            )
        self.negatives_type = negatives_type

        # добавление признаков
        self.use_generated_features = use_generated_features
        self.user_cat_features_list = user_cat_features_list
        self.item_cat_features_list = item_cat_features_list
        self.features_processor = (
            custom_features_processor if custom_features_processor else None
        )
        self.seed = seed

    def add_features(self, log, user_features, item_features, step="train"):
        self.logger.info("Feature enrichment: first-level features")
        # first-level pred and features
        full_second_level_train = log
        for idx, model in enumerate(self.first_level_models):
            current_pred = model.predict_for_pairs(
                full_second_level_train.select("user_idx", "item_idx"),
                user_features,
                item_features,
            ).withColumnRenamed("relevance", "{}_{}_rel".format(idx, model))
            full_second_level_train = full_second_level_train.join(
                current_pred, on=["user_idx", "item_idx"], how="left"
            )
            if self.use_first_level_models_feat[idx]:
                prefix = "{}_{}".format(idx, model)
                features = model.add_features(
                    full_second_level_train.select("user_idx", "item_idx"),
                    user_features,
                    item_features,
                    prefix,
                )
                full_second_level_train = full_second_level_train.join(
                    features, on=["user_idx", "item_idx"], how="left"
                )
        full_second_level_train = full_second_level_train.fillna(0).cache()

        self.logger.info(full_second_level_train.columns)

        # dataset features
        self.logger.info("Feature enrichment: dataset features")
        full_second_level_train = join_or_return(
            full_second_level_train,
            user_features,
            on_col="user_idx",
            how="left",
        )
        full_second_level_train = join_or_return(
            full_second_level_train,
            item_features,
            on_col="item_idx",
            how="left",
        )
        full_second_level_train.cache()

        self.logger.info(full_second_level_train.columns)

        # generated features
        self.logger.info("Feature enrichment: generated features")
        if self.use_generated_features:
            full_second_level_train = self.features_processor(
                full_second_level_train, step=step
            )
            self.logger.info(full_second_level_train.columns)

        return full_second_level_train

    def _split_data(self, log: DataFrame) -> Tuple[DataFrame, DataFrame]:
        first_level_train, second_level_train = self.train_splitter.split(log)
        State().logger.debug("Log info: %s", get_log_info(log))
        State().logger.debug(
            "first_level_train info: %s", get_log_info(first_level_train)
        )
        State().logger.debug(
            "second_level_train info: %s", get_log_info(second_level_train)
        )
        return first_level_train, second_level_train

    def _fit_wrap(
        self,
        log: AnyDataFrame,
        user_features: Optional[AnyDataFrame] = None,
        item_features: Optional[AnyDataFrame] = None,
        force_reindex: bool = True,
    ) -> None:
        # разбиение данных
        log, user_features, item_features = [
            convert2spark(df) for df in [log, user_features, item_features]
        ]
        self.logger.info("Разбиение данных")
        first_level_train, second_level_train = self._split_data(log)
        # индексирование
        self.logger.info("Индексирование пользователей и объектов")

        if "user_indexer" not in self.__dict__ or force_reindex:
            self._create_indexers(first_level_train, None, None)

        first_level_user_indexer, first_level_item_indexer = (
            copy.deepcopy(self.user_indexer),
            copy.deepcopy(self.item_indexer),
        )
        first_level_inv_user_indexer, first_level_inv_item_indexer = (
            copy.deepcopy(self.inv_user_indexer),
            copy.deepcopy(self.inv_item_indexer),
        )
        for model in self.first_level_models:
            model.user_indexer = copy.deepcopy(self.user_indexer)
            model.item_indexer = copy.deepcopy(self.item_indexer)
            model.inv_user_indexer = copy.deepcopy(self.inv_user_indexer)
            model.inv_item_indexer = copy.deepcopy(self.inv_item_indexer)

        log, user_features, item_features = [
            self._convert_index(df)
            for df in [log, user_features, item_features]
        ]
        self._fit(log, user_features, item_features)

    def _fit(
        self,
        log: AnyDataFrame,
        user_features: Optional[AnyDataFrame] = None,
        item_features: Optional[AnyDataFrame] = None,
        force_reindex: bool = True,
    ) -> None:
        """
        Обучает модель на логе и признаках пользователей и объектов.

        :param log: лог взаимодействий пользователей и объектов,
            спарк-датафрейм с колонками
            ``[user_id, item_id, timestamp, relevance]``
        :param user_features: признаки пользователей,
            спарк-датафрейм с колонками
            ``[user_id, timestamp]`` и колонки с признаками
        :param item_features: признаки объектов,
            спарк-датафрейм с колонками
            ``[item_id, timestamp]`` и колонки с признаками
        :param force_reindex: обязательно создавать
            индексы, даже если они были созданы ранее
        """

        for base_model in self.first_level_models:
            base_model._fit_wrap(
                first_level_train, user_features, item_features, force_reindex
            )

        self.random_model.fit(log=log, force_reindex=force_reindex)

        self.logger.info("Negatives generation")
        negatives_source = (
            self.first_level_models[0]
            if self.negatives_type == "first_level"
            else self.random_model
        )
        negatives = negatives_source.predict(
            log,
            k=self.num_negatives,
            users=log.select("user_idx").distinct(),
            items=log.select("item_idx").distinct(),
            filter_seen_items=True,
        ).withColumn("relevance", sf.lit(0.0))

        full_second_level_train = (
            second_level_train.select("user_idx", "item_idx", "relevance")
            .withColumn("relevance", sf.lit(1))
            .unionByName(negatives)
            .cache()
        )
        full_second_level_train.groupBy("relevance").agg(
            sf.count(sf.col("relevance"))
        ).show()

        self.logger.info("Feature enrichment")
        if self.features_processor is None:
            self.features_processor = TwoStagesFeaturesProcessor(
                log,
                first_level_train=first_level_train,
                second_level_train=second_level_train,
                user_features=user_features,
                item_features=item_features,
                user_cat_features_list=self.user_cat_features_list,
                item_cat_features_list=self.item_cat_features_list,
            )

        full_second_level_train = self.add_features(
            log=full_second_level_train,
            user_features=user_features,
            item_features=item_features,
            step="train",
        )

        full_second_level_train = full_second_level_train.drop(
            "user_idx", "item_idx"
        )
        self.logger.info("Convert to pandas")
        full_second_level_train_pd = full_second_level_train.toPandas()
        full_second_level_train.unpersist()

        oof_pred = self.second_stage_model.fit_predict(
            full_second_level_train_pd, roles={"target": "relevance"}
        )
        print(
            self.second_stage_model.levels[0][0]
            .ml_algos[0]
            .get_features_score()[:20]
        )

    # pylint: disable=too-many-arguments
    def predict(
        self,
        log: AnyDataFrame,
        k: int,
        users: Optional[Union[AnyDataFrame, Iterable]] = None,
        items: Optional[Union[AnyDataFrame, Iterable]] = None,
        user_features: Optional[AnyDataFrame] = None,
        item_features: Optional[AnyDataFrame] = None,
        filter_seen_items: bool = True,
    ) -> DataFrame:
        """
        Выдача рекомендаций для пользователей.

        :param log: лог взаимодействий пользователей и объектов,
            спарк-датафрейм с колонками
            ``[user_id, item_id, timestamp, relevance]``
        :param k: количество рекомендаций для каждого пользователя;
            должно быть не больше, чем количество объектов в ``items``
        :param users: список пользователей, для которых необходимо получить
            рекомендации, спарк-датафрейм с колонкой ``[user_id]`` или ``array-like``;
            если ``None``, выбираются все пользователи из лога;
            если в этом списке есть пользователи, про которых модель ничего
            не знает, то вызывается ошибка
        :param items: список объектов, которые необходимо рекомендовать;
            спарк-датафрейм с колонкой ``[item_id]`` или ``array-like``;
            если ``None``, выбираются все объекты из лога;
            если в этом списке есть объекты, про которых модель ничего
            не знает, то в ``relevance`` в рекомендациях к ним будет стоять ``0``
        :param user_features: признаки пользователей,
            спарк-датафрейм с колонками
            ``[user_id , timestamp]`` и колонки с признаками
        :param item_features: признаки объектов,
            спарк-датафрейм с колонками
            ``[item_id , timestamp]`` и колонки с признаками
        :param filter_seen_items: если True, из рекомендаций каждому
            пользователю удаляются виденные им объекты на основе лога
        :return: рекомендации, спарк-датафрейм с колонками
            ``[user_id, item_id, relevance]``
        """
        log = convert2spark(log)
        users = users or log or user_features or self.user_indexer.labels
        users = self._get_ids(users, "user_id")
        hot_data = min_entries(log, self.threshold)
        hot_users = hot_data.select("user_id").distinct()
        if self.can_predict_cold_users:
            hot_users = hot_users.join(self.hot_users)
        hot_users = hot_users.join(users, on="user_id", how="inner")

        hot_pred = self._predict_wrap(
            log=hot_data,
            k=k,
            users=hot_users,
            items=items,
            user_features=user_features,
            item_features=item_features,
            filter_seen_items=filter_seen_items,
        )
        if log is not None:
            cold_data = log.join(self.hot_users, how="anti", on="user_id")
        else:
            cold_data = None
        cold_users = users.join(self.hot_users, how="anti", on="user_id")
        cold_pred = self.cold_model._predict_wrap(
            log=cold_data,
            k=k,
            users=cold_users,
            items=items,
            user_features=user_features,
            item_features=item_features,
            filter_seen_items=filter_seen_items,
        )
        return hot_pred.union(cold_pred)

    def fit_predict(
        self,
        log: AnyDataFrame,
        k: int,
        users: Optional[Union[AnyDataFrame, Iterable]] = None,
        items: Optional[Union[AnyDataFrame, Iterable]] = None,
        user_features: Optional[AnyDataFrame] = None,
        item_features: Optional[AnyDataFrame] = None,
        filter_seen_items: bool = True,
        force_reindex: bool = True,
    ) -> DataFrame:
        """
        Обучает модель и выдает рекомендации.

        :param log: лог взаимодействий пользователей и объектов,
            спарк-датафрейм с колонками
            ``[user_id, item_id, timestamp, relevance]``
        :param k: количество рекомендаций для каждого пользователя;
            должно быть не больше, чем количество объектов в ``items``
        :param users: список пользователей, для которых необходимо получить
            рекомендации; если ``None``, выбираются все пользователи из лога;
            если в этом списке есть пользователи, про которых модель ничего
            не знает, то поднимается исключение
        :param items: список объектов, которые необходимо рекомендовать;
            если ``None``, выбираются все объекты из лога;
            если в этом списке есть объекты, про которых модель ничего
            не знает, то в рекомендациях к ним будет стоять ``0``
        :param user_features: признаки пользователей,
            спарк-датафрейм с колонками
            ``[user_id , timestamp]`` и колонки с признаками
        :param item_features: признаки объектов,
            спарк-датафрейм с колонками
            ``[item_id , timestamp]`` и колонки с признаками
        :param filter_seen_items: если ``True``, из рекомендаций каждому
            пользователю удаляются виденные им объекты на основе лога
        :param force_reindex: обязательно создавать
            индексы, даже если они были созданы ранее
        :return: рекомендации, спарк-датафрейм с колонками
            ``[user_id, item_id, relevance]``
        """
        self.fit(log, user_features, item_features, force_reindex)
        return self.predict(
            log,
            k,
            users,
            items,
            user_features,
            item_features,
            filter_seen_items,
        )

    # pylint: disable=too-many-arguments, too-many-locals
    def optimize(
        self,
        train: AnyDataFrame,
        test: AnyDataFrame,
        user_features: Optional[AnyDataFrame] = None,
        item_features: Optional[AnyDataFrame] = None,
        param_grid: Optional[Dict[str, Dict[str, List[Any]]]] = None,
        criterion: Metric = NDCG(),
        k: int = 10,
        budget: int = 10,
    ) -> Tuple[Dict[str, Any]]:
        """
        Подбирает лучшие гиперпараметры с помощью optuna для обоих моделей
        и инициализирует эти значения.

        :param train: датафрейм для обучения
        :param test: датафрейм для проверки качества
        :param user_features: датафрейм с признаками пользователей
        :param item_features: датафрейм с признаками объектов
        :param param_grid: словарь с ключами main, cold, и значеними в виде сеток параметров.
            Сетка задается словарем, где ключ ---
            название параметра, значение --- границы возможных значений.
            ``{param: [low, high]}``.
        :param criterion: метрика, которая будет оптимизироваться
        :param k: количество рекомендаций для каждого пользователя
        :param budget: количество попыток при поиске лучших гиперпараметров
        :return: словари оптимальных параметров
        """
        if param_grid is None:
            param_grid = {"main": None, "cold": None}
        self.logger.info("Optimizing main model...")
        params = self._optimize(
            train,
            test,
            user_features,
            item_features,
            param_grid["main"],
            criterion,
            k,
            budget,
        )
        if not isinstance(params, tuple):
            self.set_params(**params)
        if self.cold_model._search_space is not None:
            self.logger.info("Optimizing cold model...")
            cold_params = self.cold_model._optimize(
                train,
                test,
                user_features,
                item_features,
                param_grid["cold"],
                criterion,
                k,
                budget,
            )
            if not isinstance(cold_params, tuple):
                self.cold_model.set_params(**cold_params)
        else:
            cold_params = None
        return params, cold_params
