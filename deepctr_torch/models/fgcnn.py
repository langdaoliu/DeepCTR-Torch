# -*- coding:utf-8 -*-
"""
Author:
    Wutong Zhang
Reference:
    [1] Liu B, Tang R, Chen Y, et al. Feature Generation by Convolutional Neural Network for Click-Through Rate Prediction[J]. arXiv preprint arXiv:1904.04447, 2019.
    (https://arxiv.org/pdf/1904.04447)
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
import pdb
import time
from .basemodel import BaseModel
from ..layers import FGCNNLayer, DNN, InnerProductLayer
class FGCNN(BaseModel):
    """Instantiates the Feature Generation by Convolutional Neural Network architecture.
    :param dnn_feature_columns: An iterable containing all the features used by deep part of the model.    :param embedding_size: positive integer,sparse feature embedding_size
    :param conv_kernel_width: list,list of positive integer or empty list,the width of filter in each conv layer.
    :param conv_filters: list,list of positive integer or empty list,the number of filters in each conv layer.
    :param new_maps: list, list of positive integer or empty list, the feature maps of generated features.
    :param pooling_width: list, list of positive integer or empty list,the width of pooling layer.
    :param dnn_hidden_units: list,list of positive integer or empty list, the layer number and units in each layer of deep net.
    :param l2_reg_embedding: float. L2 regularizer strength applied to embedding vector
    :param l2_reg_dnn: float. L2 regularizer strength applied to DNN
    :param dnn_dropout: float in [0,1), the probability we will drop out a given DNN coordinate.
    :param init_std: float,to use as the initialize std of embedding vector
    :param seed: integer ,to use as random seed.
    :param task: str, ``"binary"`` for  binary logloss or  ``"regression"`` for regression loss
    :return: A PyTorch model instance.
    """
    def __init__(self,
                 dnn_feature_columns, embedding_size=8, conv_kernel_width=(7, 7, 7, 7), conv_filters=(14, 16, 18, 20),
                 new_maps=(3, 3, 3, 3),
                 pooling_width=(2, 2, 2, 2), dnn_hidden_units=(128,), dnn_activation=F.relu, l2_reg_embedding=1e-5, l2_reg_dnn=0,
                 dnn_dropout=0,
                 init_std=0.0001, seed=1024,
                 task='binary', device='cpu'):
        super(FGCNN, self).__init__(dnn_feature_columns, dnn_feature_columns, embedding_size=embedding_size,
                                     dnn_hidden_units=dnn_hidden_units,
                                     l2_reg_embedding=l2_reg_embedding, l2_reg_dnn=l2_reg_dnn, init_std=init_std,
                                     seed=seed,
                                     dnn_dropout=dnn_dropout,
                                     task=task, device=device)
        self.conv_filters = conv_filters
        self.conv_kernel_width = conv_kernel_width
        self.new_maps = new_maps
        self.pooling_width = pooling_width
        self.embedding_size = embedding_size
        self.fg_embedding_dict = self.create_embedding_matrix(dnn_feature_columns, embedding_size, init_std,
                                                           sparse=False).to(device)
        self.deep_embedding_dict = self.create_embedding_matrix(dnn_feature_columns, embedding_size, init_std,
                                                           sparse=False).to(device)
        self.add_regularization_loss(
            self.fg_embedding_dict.parameters(), l2_reg_embedding)
        self.add_regularization_loss(
            self.deep_embedding_dict.parameters(), l2_reg_embedding)
        self.field_size = len(self.fg_embedding_dict)
        self.fgcnn = FGCNNLayer(self.field_size, self.embedding_size,
                                self.conv_filters, self.conv_kernel_width, self.new_maps, self.pooling_width, device=device)
        self.innerproduct = InnerProductLayer(device=device)
        self.combined_feture_num = self.fgcnn.new_feture_num + self.field_size
        self.dnn_input_dim = self.combined_feture_num * (self.combined_feture_num - 1) // 2\
                                + self.combined_feture_num * self.embedding_size
        self.dnn = DNN(self.dnn_input_dim, dnn_hidden_units,
                       activation=dnn_activation, l2_reg=l2_reg_dnn, dropout_rate=dnn_dropout,
                       init_std=init_std, device=device)
        self.dnn_linear = nn.Linear(dnn_hidden_units[-1], 1, bias=False).to(device)
        self.add_regularization_loss(
            filter(lambda x: 'weight' in x[0] and 'bn' not in x[0], self.dnn.named_parameters()), l2_reg_dnn)
        self.add_regularization_loss(self.dnn_linear.weight, l2_reg_dnn)
        self.to(device)

    def forward(self, X):

        fg_sparse_embedding_list, fg_dense_value_list = self.input_from_feature_columns(X, self.dnn_feature_columns,
                                                                     self.fg_embedding_dict)
        deep_sparse_embedding_list, deep_dense_value_list = self.input_from_feature_columns(X, self.dnn_feature_columns,
                                                                     self.deep_embedding_dict)
        fg_input = torch.cat(fg_sparse_embedding_list, dim=1)
        origin_input = torch.cat(deep_sparse_embedding_list, dim=1)
        if len(self.conv_filters) > 0:
            new_features = self.fgcnn(fg_input)
            combined_input = torch.cat([origin_input, new_features], dim=1)
        else:
            combined_input = origin_input
        inner_product = torch.flatten(self.innerproduct(torch.split(combined_input, 1, dim=1)),start_dim=1)
        linear_signal = torch.flatten(combined_input,start_dim=1)
        dnn_input = torch.cat([linear_signal, inner_product], dim=1)
        dnn_output = self.dnn(dnn_input)
        final_logit = self.dnn_linear(dnn_output)
        y_pred = self.out(final_logit)
        return y_pred
