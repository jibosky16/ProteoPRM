import torch
import peptdeep.model.building_block as building_block
class Model(torch.nn.Module):
    def __init__(self,
        dropout=0.2,
    ):
        """
        Model based on a combined CNN/LSTM architecture
        """
        super().__init__()

        self.dropout = torch.nn.Dropout(dropout)

        hidden = 256
        self.rt_encoder = building_block.Encoder_AA_Mod_CNN_LSTM_AttnSum(
            hidden
        )

        self.rt_decoder = building_block.Decoder_Linear(
            hidden,
            1
        )

    def forward(self,
        aa_indices,
        mod_x,
    ):
        x = self.rt_encoder(aa_indices, mod_x)
        x = self.dropout(x)

        return self.rt_decoder(x).squeeze(1)
