"""
Subnet Hyperparameters
NETUID: 19 - Network: finney

rho                              10                     10
kappa                            32767                  0.4999923705
immunity_period                  7000                   7000
min_allowed_weights              1                      1
max_weight_limit                 65535                  1
tempo                            360                    360
min_difficulty                   18446744073709551615   1
max_difficulty                   18446744073709551615   1
weights_version                  60000                  60000
weights_rate_limit               100                    100
adjustment_interval              360                    360
activity_cutoff                  20000                  20000
registration_allowed             True                   True
target_regs_per_interval         1                      1
min_burn                         100                    τ0.000000100
max_burn                         100000000000           τ100.000000000
bonds_moving_avg                 900000                 4.878909776e-14
max_regs_per_block               1                      1
serving_rate_limit               50                     50
max_validators                   64                     64
adjustment_alpha                 14757395258967642112   0.8
difficulty                       18446744073709551615   1
commit_reveal_weights_interval   1                      1
commit_reveal_weights_enabled    False                  False
alpha_high                       58982                  0.9000076295
alpha_low                        45875                  0.7000076295
liquid_alpha_enabled             False                  False
"""
from pydantic import BaseModel, ConfigDict, Field


class HyperparametersDTO(BaseModel):
    """Data transfer object for block hyperparameters."""

    model_config = ConfigDict(frozen=True)

    rho: int
    kappa: float
    immunity_period: int
    min_allowed_weights: int
    max_weight_limit: float = Field(alias="max_weights_limit")
    tempo: int
    min_difficulty: int
    max_difficulty: int
    weights_version: int
    weights_rate_limit: int
    adjustment_interval: int
    activity_cutoff: int
    registration_allowed: bool
    target_regs_per_interval: int
    min_burn: int
    max_burn: int
    bonds_moving_avg: float
    max_regs_per_block: int
    serving_rate_limit: int
    max_validators: int
    adjustment_alpha: float
    difficulty: int
    commit_reveal_weights_interval: int = Field(default=1, alias="commit_reveal_period")
    commit_reveal_weights_enabled: bool
    alpha_high: float
    alpha_low: float
    liquid_alpha_enabled: bool
    validator_prune_len: int = 0
    scaling_law_power: int = 0
    synergy_scaling_law_power: int = 0
    subnetwork_n: int = 0
    max_allowed_uids: int = 0
    blocks_since_last_step: int = 0
    block_number: int = 0

    def to_table_rows(self) -> list[tuple[str, str]]:
        """Format hyperparameters as table rows for Rich display."""
        rows = []
        for field_name, value in self.model_dump().items():
            if isinstance(value, float):
                # Format floats based on magnitude
                formatted_value = f"{value:.15e}" if abs(value) < 0.01 or abs(value) > 1000 else f"{value:.10f}"
            else:
                formatted_value = str(value)
            rows.append((field_name, formatted_value))
        return rows
