# User Stories

What Sentinel's users can do: people reading its Grafana dashboards, receiving its Discord alerts and browsing its admin. Only user stories belong here; [AGENTS.md](AGENTS.md#user-stories) says what qualifies and how to write one. How the data is collected, setup and operations are in [README.md](README.md) and [docs/](docs/).

## Dashboards

### Validator returns

As a validator operator, I see my validator's APY computed from actual per-epoch dividends and stake, so that I can verify my returns without building the calculation myself.

- The **Subnet APY** dashboard shows APY per validator and subnet over time.
- Numbers stay fresh within minutes of new epochs.

### Neurons over time

As a subnet owner or miner, I follow my neurons' stake, incentive and emissions over time, so that I can see how my subnet and miners perform.

- **Metagraph Miner**, **Metagraph Multi-miner**, **Metagraph Validator** and **Metagraph Subnet** show snapshots taken at the start, middle and end of each epoch.
- In **Metagraph Subnet**, each hotkey opens its Miner (and, for validators, Validator) dashboard for the same subnet and time range.
- Known keys show a name instead of an address: a manual label first, otherwise the coldkey's on-chain identity.

### Burns and emissions

As an analyst, I see for every subnet how much of its incentive goes back to the owner's own coldkey and whether emissions were enabled, so that I can tell which subnets pay their miners and which pay themselves.

- **Burns and Emissions** lines all subnets up on the same epochs in one heatmap.
- A burn is attributed to whoever owned the subnet at that time, so a change of owner does not rewrite history.
- The same measurement is available for one separately configured coldkey ("superburn").

### Hyperparameters and weights

As a subnet owner or researcher, I see every subnet's current hyperparameters and the history of their changes, so that I can follow governance decisions over time.

- **Subnet Hyperparameters** shows current values and each change with its old and new value.
- **Weight Setting** and **Subnets** give an overview of weight-setting activity and subnets.

## Alerts

### Governance alerts on Discord

As a subnet owner or governance watcher, I get a Discord alert when something governance-relevant happens on chain, so that I can react without watching the chain myself.

- Alerts cover subnet registration and dissolution, coldkey swap announcements, disputes, resets and clears, hyperparameter changes (with old and new value), and any other sudo call.
- Calls made through sudo or a multisig are alerted like the same call sent directly, naming the multisig and the member who executed it.
- Only calls that succeeded on chain are alerted.

### Alerts for my subnet

As an administrator, I route a subnet's alerts to its owner's own Discord webhook and pause it when needed, so that owners hear about their subnet without a code change.

- Webhooks are managed per subnet in Django admin.
- A webhook can be disabled temporarily without losing its configuration.

## Admin

### Exploring chain data

As an admin user, I inspect a subnet's full metagraph at any recorded block and search extrinsics, so that I can investigate a specific moment or transaction without writing SQL.

- I pick a subnet and one of the blocks that were actually recorded for it.
- Extrinsics can be filtered by call module, success and subnet, and searched by hash, address or call function.
