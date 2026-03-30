import torch
import peptdeep.model.building_block as building_block
from peptdeep.model.model_shop import *
class Model(
    Model_for_Generic_ModAASeq_Regression_Transformer
):
    """Generic transformer classification model for modified sequence"""

    def __init__(
        self,
        *,
        hidden_dim=256,
        output_dim=1,
        nlayers=4,
        output_attentions=False,
        dropout=0.1,
        **kwargs,
    ):
        super().__init__(
            nlayers=nlayers,
            hidden_dim=hidden_dim,
            output_dim=output_dim,
            output_attentions=output_attentions,
            dropout=dropout,
            **kwargs,
        )

    @property
    def output_attentions(self) -> bool:
        return self._output_attentions

    @output_attentions.setter
    def output_attentions(self, val: bool):
        self._output_attentions = val

    def forward(
        self,
        aa_indices,
        mod_x,
    ):
        x = super().forward(aa_indices, mod_x)
        return torch.sigmoid(x)
