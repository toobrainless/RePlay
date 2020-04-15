"""
Данный модуль содержит обертки для известных моделей, вроде LightFM,
и реализует некоторые классические алгоритмы.

Модели используют в реализации либо Spark, либо pytorch.
"""

from sponge_bob_magic.models.als import ALS
from sponge_bob_magic.models.base_rec import Recommender
from sponge_bob_magic.models.knn import KNN
from sponge_bob_magic.models.lightfm import LightFMWrap
from sponge_bob_magic.models.linear import Linear
from sponge_bob_magic.models.mlp import MLPRec
from sponge_bob_magic.models.neuromf import NeuroMF
from sponge_bob_magic.models.pop_rec import PopRec
from sponge_bob_magic.models.random_pop import RandomPop
from sponge_bob_magic.models.slim import SLIM
from sponge_bob_magic.models.mult_vae import MultVAE
