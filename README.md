# RePlay
Библиотека RePlay содержит инструменты для создания рекомендательных систем от предобработки данных до выбора лучшего решения. 
В Replay используется Spark, чтобы эффективно работать с большими датасетами.

RePlay поможет:
* Отфильтровать и разбить данные для обучения рекомендательной системы
* Обучить модель
* Подобрать гиперпараметры
* Оценить качество и сравнить модели
* Объединить рекомендации, полученные несколькими моделями


## Начало работы
Примеры использования библиотеки в директории `/experiments`.


## Алгоритмы, реализованные в RePlay

**Базовые алгоритмы**

| Алгоритм       | Реализация обучения |Описание |
| ---------------|---------------------|-------|
|Popular Recommender        |PySpark                | Рекомендует популярные объекты (встречавшиеся в истории взаимодействия чаще остальных)    |
|Popular By Users           |PySpark                | Рекомендует объекты, которые пользователь ранее выбирал чаще всего |
|Wilson Recommender         |Python CPU             | Рекомендует объекты с лучшими оценками. Оценка объекта определяется как нижняя граница доверительного интервала Уилсона для доли положительных взаимодействий     |
|Random Recommender         |PySpark                | Рекомендует случайные объекты или сэмплирует с вероятностью, пропорциональной популярности объекта   |
|K-Nearest Neighbours       |PySpark                | Рекомендует объекты, похожие на те, с которыми взаимодействовал пользователь
|Classifier Recommender     |PySpark                | Алгоритм бинарной классификации для релевантности объекта для пользователя по их признакам          |
|Alternating Least Squares  |PySpark                | Алгоритм матричной факторизации [Collaborative Filtering for Implicit Feedback Datasets](https://ieeexplore.ieee.org/document/4781121)           |
|Neural Matrix Factorization|Python CPU/GPU         | Алгоритм нейросетевой матричной факторизации на базе [Neural Collaborative Filtering](https://arxiv.org/pdf/1708.05031.pdf)          |
|SLIM                       |PySpark                | Алгоритм, обучающий матрицу близости объектов для восстановления матрицы взаимодействия [SLIM: Sparse Linear Methods for Top-N Recommender Systems](http://glaros.dtc.umn.edu/gkhome/fetch/papers/SLIM2011icdm.pdf)          |
|ADMM SLIM                  |Python CPU             | Улучшение стандартного алгоритма SLIM, [ADMM SLIM: Sparse Recommendations for Many Users](http://www.cs.columbia.edu/~jebara/papers/wsdm20_ADMM.pdf)          |
|MultVAE                    |Python CPU/GPU         | Вариационный автоэнкодер, восстанавливающий вектор взаимодействий для пользователя [Variational Autoencoders for Collaborative Filtering](https://arxiv.org/pdf/1802.05814.pdf)          |
|Word2Vec Recommender       |Python CPU/GPU         | Рекомендатель на основе word2vec, в котором объекты сопоставляются словам, а пользователи - предложениям          |
|Обертка LightFM            |Python CPU             | Обертка для обучения моделей [LightFM](https://making.lyst.com/lightfm/docs/home.html)          |
|Обертка Implicit           |Python CPU             | Обертка для обучения моделей [Implicit](https://implicit.readthedocs.io/en/latest/)          |

Для всех базовых алгоритмов выдача рекоментаций (inference) реализована с использованием PySpark.

**Многоуровневые алгоритмы**

| Алгоритм       | Реализация |  Описание |
| ---------------|--------------------|-------|
|Stack Recommender          | `*`  | Модель стекинга, перевзвешивающая предсказания моделей первого уровня        |
|Двухуровневый классификатор| `*`  | Классификатор, использующий для обучения эмбеддинги пользователей и объектов, полученные базовым алгоритмом (например, матричной факторизацией), и признаки пользователей и объектов, переданные пользователем   |

`*` - зависит от алгоритмов, используемых в качестве базовых. 
Выбор алгоритма рекомендательной системы зависит от данных и требований пользователя к рекомендациям, подробнее в документации RePlay.


## Метрики
В библиотеке реализованы метрики для оценки качества классификации и ранжирования, а также специализированные метрики для рекомендательных систем, важные для оценки достижения бизнес-целей системы.
Метрики можно посчитать для различных значений _k_ (числа рекомендаций, учитываемых при расчете метрики), оценить среднее/медианное значение метрики по пользователям или нижнюю границу доверительного интервала метрики.  

| Метрика       | Описание | Тип метрики | Дополнительные параметры | 
| ---------------|--------------|-------|-------|
|HitRate                      | Доля пользователей, для которых хотя бы одна рекомендация из первых K релевантна. | Классификация |  |
|Precision                    | Доля релевантных рекомендаций среди первых K элементов выдачи. | Классификация |  |
|Mean Average Precision, MAP  | Средний Precision по всем j <= K элементам выдачи. | Ранжирование |
|Recall                       | Доля объектов из тестовой выборки, вошедших в первые K рекомендаций алгоритма. | Классификация |
|ROC-AUC                      | Доля правильно упорядоченных (релевантный / нерелевантный) пар объектов среди рекомендованных. | Ранжирование |
|Mean Reciprocal Rank, MRR    |  Средняя позиция первой релевантной рекомендации из K элементов выдачи в степени -1. | Ранжирование |
|Normalized Discounted Cumulative Gain, NDCG| Метрика ранжирования, учитывающая позиции релевантных объектов среди первых K элементов выдачи. | Ранжирование |
|Surprisal                    | Степень "редкости" (непопулярности) рекомендуемых объектов | Разнообразие | Лог взаимодействия для определения степени редкости объектов|
|Unexpectedness               | Доля рекомендуемых объектов, которые не содержатся в рекомендациях базового алгоритма | Разнообразие | Базовый алгоритм и лог взаимодействия для обучения или рекомендации базового алгоритма|
|Coverage                     | Доля объектов, которые встречаются в полученных рекомендациях| Разнообразие | Лог взаимодействия, содержащий все доступные объекты|

Более подробную информацию о метриках и формулах для их расчета можно найти в документации к RePlay.


## Эксперименты
Класс Experiment позволяет посчитать метрики для рекомендаций, полученных несколькими моделями, и сравнить их. 


## Сценарии
В RePlay реализованы сценарии — пайплайны, объединяющие применение нискольких модулей библиотеки, включая:
* разбиение данных на обучающую и валидационную выборки
* автоматический подбор гиперпараметров моделей
* расчёт метрик и сравнение моделей
* обучение на всём объёме данных и построение рекомендаций

## Как начать пользоваться библиотекой

### Установка
Для корректной работы необходимы python 3.6+ и java 8+. \

Клонируйте репозиторий RePlay: \
 в _sigma_:
```bash
git clone https://sbtatlas.sigma.sbrf.ru/stash/scm/ailab/replay.git
```
в _alpha_:
```bash
git clone ssh://git@stash.delta.sbrf.ru:7999/ailabrecsys/replay.git
```
 и установите библиотеку с помощью poetry:
```
cd replay
pip install --upgrade pip
pip install poetry
poetry install
```

### Проверка работы библиотеки
Запустите тесты для проверки корректности установки. \
Из директории `replay`:
```bash
pytest ./tests
```

### Документация

Запустите формирование документации из директории `replay`:
```bash
cd ./docs
mkdir -p _static
make clean html
```
Документация будет доступна в `replay/docs/_build/html/index.html`

## Как присоединиться к разработке
[Инструкция для разработчика](README_dev.md)
