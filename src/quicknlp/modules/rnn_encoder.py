import warnings

import torch.nn as nn

from fastai.lm_rnn import EmbeddingDropout, LockedDropout
from .cell import Cell


def get_layer_dims(layer_index, total_layers, in_dim, out_dim, nhid, bidir):
    ndir = 2 if bidir else 1
    input_size = in_dim if layer_index == 0 else nhid
    output_size = (nhid if layer_index != total_layers - 1 else out_dim) // ndir
    return input_size, output_size


class RNNEncoder(nn.Module):
    """
    Wrote this class to allow for a multilayered RNN encoder. It follows the fastai RNN_Encoder class
    """

    initrange = 0.1

    def __init__(self, ntoken, emb_sz, nhid, nlayers, pad_token, dropouth=0.3, dropouti=0.65, dropoute=0.1, wdrop=0.5,
                 bidir=False, cell_type="lstm", **kwargs):
        """ Default Constructor for the RNNEncoder class

        Args:
            ntoken (int): number of vocabulary (or tokens) in the source dataset
            emb_sz (int): the embedding size to use to encode each token
            nhid (int): number of hidden activation per LSTM layer
            nlayers (int): number of LSTM layers to use in the architecture
            pad_token (int): the int value used for padding text.
            dropouth (float): dropout to apply to the activations going from one LSTM layer to another
            dropouti (float): dropout to apply to the input layer.
            dropoute (float): dropout to apply to the embedding layer.
            wdrop (float): dropout used for a LSTM's internal (or hidden) recurrent weights.
            cell_type (str): Type of cell (default is LSTM)
        """
        super(RNNEncoder, self).__init__()
        self.encoder = nn.Embedding(ntoken, emb_sz, padding_idx=pad_token)
        self.encoder_with_dropout = EmbeddingDropout(self.encoder)
        self.rnns = []
        for layer_index in range(nlayers):
            input_size, output_size = get_layer_dims(layer_index=layer_index, total_layers=nlayers,
                                                     in_dim=kwargs.get("in_dim", emb_sz),
                                                     out_dim=kwargs.get("out_dim", emb_sz),
                                                     nhid=nhid, bidir=bidir)
            self.rnns.append(
                Cell(cell_type=cell_type, input_size=input_size, output_size=output_size,
                     bidir=bidir, dropouth=dropouth, wdrop=wdrop)
            )

        self.rnns = nn.ModuleList(self.rnns)
        self.encoder.weight.data.uniform_(-self.initrange, self.initrange)
        self.emb_sz, self.nhid, self.nlayers, self.dropoute, self.bidir = emb_sz, nhid, nlayers, dropoute, bidir
        self.dropouti = LockedDropout(dropouti)
        self.dropouths = nn.ModuleList([LockedDropout(dropouth) for l in range(nlayers)])
        self.reset(1)

    def forward(self, input):
        """ Invoked during the forward propagation of the RNN_Encoder module.
        Args:
            input (Tensor): input of shape (batch_size x sentence length)

        Returns:
            (Tuple[List[Tensor], List[Tensor]]):
            raw_outputs: list of tensors evaluated from each RNN layer without using dropouth,
            outputs: list of tensors evaluated from each RNN layer using dropouth,
            The outputs should have dims [sl,bs,layer_dims]
        """
        # we reset at very batch as they are not sequential (like a languagemodel)
        # sl, self.bs = input.size()

        emb = self.encoder_with_dropout(input, dropout=self.dropoute if self.training else 0)
        emb = self.dropouti(emb)

        raw_output = emb
        new_hidden, raw_outputs, outputs = [], [], []
        for l, (rnn, drop) in enumerate(zip(self.rnns, self.dropouths)):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw_output, new_h = rnn(raw_output, self.hidden[l])
            new_hidden.append(new_h)
            raw_outputs.append(raw_output)
            if l != self.nlayers - 1: raw_output = drop(raw_output)
            outputs.append(raw_output)

        self.hidden = new_hidden
        return raw_outputs, outputs

    def reset(self, bs):
        self.weights = next(self.parameters()).data
        self.hidden = [self.rnns[l].hidden_state(bs) for l in range(self.nlayers)]
