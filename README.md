# Powershop NZ — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/pshemk/powershopnz.svg)](https://github.com/pshemk/powershopnz/releases)
![Zip downloads](https://img.shields.io/github/downloads/pshemk/powershopnz/total.svg)

A Home Assistant custom integration that pulls data from your Powershop New Zealand account. 

##  Disclaimer

This is not an official integration provided by Powershop NZ. It simply uses their API to extract the data. 

## Requirements

Your account must be accessible via the new Powershop (Powershop Labs) app.

## Features

### Current price sensors

A sensor that reports the current price of a kWh. In addition to the nominal price there's also an effective price sensor that takes into consideration all the purchased (and available) powerpacks. These sensors can be used to provide price information to the Dynamic Energy Cost integration.

### Current rate type sensor

A sensor that reports the current rate type  (peak, off-peak, or any other returned by the Powershop API). This sensor can be used to trigger automations during lower-cost periods. It's worth noting that there might be multiple rates to cover the same type of tariff. For example, my own home connection has two rates: All Weekend Off Peak and Weekday Off Peak that are priced the same. This integration doesn't combine them, so if you need a simple peak/off-peak switch - use a template sensor that checks the current value of this sensor and report accordingly. 

### Side-loading of historical information

Past power usage and costs are available to Home Assistant as statistics. That means that the historical information can be used to populate the fantastic Energy Dashboard. The historical information includes both usage and cost. The usage is also split into the various rates that are available to your account.

### Highly customisable

Sensor groups can be disabled via the options menu if not needed. 

## Installation process

This integration can be installed using HACS custom integration:

1. Open HACS 
2. In the top-right corner click the three dots menu and select "Custom repository"
3. In the Repository field paste `https://github.com/pshemk/powershopnz`
4. In the Type field select "Integration" 
5. Click "Add"
6. Once the integration is added, go to Home Assistant "Settings" -> "Devices & Services" 
7. Click "Add Integration" at the bottom right
8. Search for "Powershop NZ" in the window that appears and click it
9. Follow the prompts of the installation process

The icon currently doesn't work in HACS, due to a bug in HACS. 

<!-- [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pshemk&repository=https%3A%2F%2Fgithub.com%2Fpshemk%2Fpowershopnz&category=Integration) -->

## Sensors

The integration provides the following regular sensors. All entities are in the `sensor.` domain.

| Name | Entity | Description | Unit | Update frequency|
|------|--------|-------------|------|-------------|
| Billing period cost: Effective Total |  `powershopnz_billing_period_`<br>`cost_total_effective` | The cost of electricity in current billing period including powerpacks discounts | NZD | 10 mins | 
| Billing period cost: Nominal Total | `powershopnz_billing_period_`<br>`cost_total_nominal` | The cost of electricity in current billing period using nominal pricing | NZD | 10 mins | 
| Billing period days so far | `powershopnz_billing_period_`<br>`usage_daily_charge` | Number of days in the billing period with usage data so far | days | 10 mins | 
| Billing period usage: Total | `powershopnz_billing_period_`<br>`usage_total` | Total power usage in the current billing period | kWh | 10 mins | 
| Billing period usage: Rate name | `powershopnz_billing_period_`<br>`usage_[*rate_name*]` | Total power usage in the current  billing period during given rate period | kWh | 10 mins | 
| Current billing period start date | `powershopnz_current_billing_period_`<br>`start_date` | The first timestamp of the current billing period | date-time | 5 mins | 
| Current billing period end date | `powershopnz_current_billing_period_`<br>`end_date` | The last timestamp of the current billing period | date-time | 5 mins | 
| Next billing date | `powershopnz_current_next_`<br>`billing_date` | The first timestamp of the next billing period | date-time | 5 mins | 
| Current rate type | `powershopnz_unit_rate_type` | Current rate type (peak, off-peak, night, etc) | 30 sec | 
| Daily charge | `powershopnz_daily_charge` | Daily charge | NZD | 5 mins | 
| Effective cost ratio | `powershopnz_effective_`<br>`cost_ratio` | The proportion of the nominal cost of the units of power including powerpacks discounts | no unit | 10 mins | 
| Effective rate | `powershopnz_effective_`<br>`unit_cost` | The cost of units of power including powerpacks discounts at current time| NZD |  10 mins | 
| Effective rate: Rate name | `powershopnz_effective_`<br>`unit_cost_[*rate_name*]` | The cost of units of power including powerpacks discounts during given rate period | NZD | 10 mins |
| Nominal rate | `powershopnz_nominal_`<br>`unit_cost` | The cost of units of power using nominal pricing at current time| NZD | 5 mins | 
| Nominal rate: Rate name | `powershopnz_nominal_`<br>`unit_cost_[*rate_name*]` | The cost of units of power using nominal pricing during given rate period | NZD | 5 mins | 
| Powerpacks: available balance | `powershopnz_powerpacks_`<br>`available_balance` | The sum value of currently available powerpacks | NZD | 5 mins |
| Powerpacks: future balance | `powershopnz_powerpacks_`<br>`future_balance` | The sum value of powerpacks that will be available in future | NZD | 5 mins |
| Previous billing period cost: Effective Total |  `powershopnz_previous_billing_period_`<br>`cost_total_effective` | The cost of electricity in previous billing period including powerpacks discounts | NZD | 10 mins | 
| Previous billing period cost: Nominal Total | `powershopnz_previous_billing_period_`<br>`cost_total_nominal` | The cost of electricity in previous billing period using nominal pricing | NZD | 10 mins | 
| Previous billing period usage: Total | `powershopnz_previous_billing_period`<br>`_usage_total` | Total power usage in the previous billing period | kWh | 10 mins | 


In addition to the sensors above the following sensors are also created. They are used to store the historical values based on usage pulled using the API. Since the API doesn't return current (or up to date) values these sensors always report their values as `unknown`, but they provide all the statistical values and can be used for graphing (or in the energy dashboard). The resolution of each sensor is 1h. Technically they only exist to provide placeholders for the long-term statistics.

| Name | Entity | Description | Unit |
|------|--------|-------------|------|
| Nominal power cost | `powershopnz_historical_`<br>`nominal_cost_total` | The total cost of energy (using nominal rates) | NZD | 
| Effective power cost | `powershopnz_historical_`<br>`nominal_cost_total` | The total cost of energy (using effective rates) | NZD | 
| Nominal power cost Rate name | `powershopnz_historical_`<br>`nominal_cost_[*rate_name*]` | The  cost of energy used during given rate period (using nominal rates) | NZD |
| Power usage | `powershopnz_historical_`<br>`usage_total` | The total usage of energy | kWh | 
| Power usage Rate name | `powershopnz_historical_`<br>`usage_[*rate_name*]` | The usage of energy  during given rate period | kWh |

### Attributes

The following sensors provide additional information through attributes:

| Name | Attribute | Description |
|------|-----------|-------------|
| Billing period cost: Effective Total | `powerpacks` | List of powerpacks that will be used to achieve the effective cost |
| Powerpacks: available balance | `powerpacks`| List of available powerpacks |
| Powerpacks: future balance | `powerpacks` | List of powerpacks that will be available in future | 

## Calculations of the effective rates

These calulcations are done entirely in the integration (i.e. the API doesn't provide anything discounted pricing information beyond the purchased powerpacks). Each powerpack has an inherit discount rate (for example if you purchased it for $10 but it covers $20 of power the rate is 0.5). The "Staying Power" are generally 0.75 to 0.8 and the future packs are around 0.9 (those rates can be seen in the attribures of the "Powerpacks" sensors). The special powerpacks vary wildly, sometimes as low as 0.5. 

When another day of usage data for the biling period is made available the intgration identifies the powerpacks that offer the best rates and calculates the total amount of money spent on those powerpacks. Than, the daily charge for that period is substracted (using nominal rates) resulting in total amount of money spent on energy alone. A calculation is also done for the nominal power rates over the same period of time.  Than the powerpack usage costs are divided by the nominal usage costs. The result is stored in the `Effective cost ratio` sensor. For each new day the whole calculation is repeated (each time usage data is taken from the start of the billing period). That effective cost ratio is than used to calculate various "effective" rates. All those rates are indicative only, as they're only valid for that one day. Only the last day of the billing cycle offers a true insight into the discounts. 


## Notes

During the first run the integration attempts to download all available usage information. That might take a few minutes to complete. Only once the data has been downloaded the sensor values are be populated. 

The effective rates and costs are recalculated every time a powerpack is purchased or past usage information is made available by Powershop. That means that the rate fluctuates as consumption changes and tends to decrease as the days of the billing period progress if you keep buying the special powerpacks. If there's no usage data for the billing period yet, the ratio remains at 1. The daily effective rate (and the historical effective power cost) changes daily and only provides an approximate cost throughout the billing period, becoming most accurate on the last day of the billing period. The  "effective cost per day" calculated for the previous days of the biling period is never updated once stored.

The effective cost ratio is calculated only using the costs of units (kWh) of energy. The daily charge always remains unaffected by the ratio, which is the same way Powershop presents their "special" rates.

All costs are calculated in the integration, so there might be some small differences when it comes to nominal costs due to rounding. It's done this way because downloading both costs and usage seems to be much slower than downloading the usage alone; also, calculating the costs in the integration makes it easier to calculate the effective costs. 

The historical data is always with 1h resolution, but due to the way it's loaded (using the historical sensor) it don't behave exactly the same way regular sensors do. The most important difference is that they never have the current value, hence they can only be used for statistical purposes.  Please have a look at the examples. 

The billing period always rolls over into the next one before all data is available (powerpacks are "consumed" on the last day of the billing cycle when there's still no usage information for the last day). The billing period data then become available in the 'Previous billing' sensors. 

The way power prices are structured varies widely across the country. The types of rates as well as meter setups are different between different local lines companies. The integration pulls all that data from the API, but that also means that there's no easy way of testing all of the possible setups.  I live in West Auckland on Vector's network and that's what I've been testing with. If you're in a different part of the country and the integration doesn't work for you - please open an issue. 

## Known issues

1. Switching between rates (peak/off-peak/night) doesn't happen at the exact times. The integration updates the sensor with the current rate type every 30 seconds. 
2. Historical data that's loaded into statistics (like past power usage or past cost) can not be back-filled  once stored. Since Powershop doesn't always release past usage information in a chronological order newer data always blocks older data from being stored. That leads to gaps in the statistics. So far I have not found a user-friendly workaround. Deleting the integration does not delete the statistics from Home Assistant either. The only way to delete them right now is to delete them from the database directly. 
3. The accuracy of the  information about past billing cycle is not great until the current billing cycle become the past one. That's because a lot of historical information (like past rates or already consumed powerpacks) are not accessible via the API. This integration stores all the information and as the time progresses and after two full billing cycles the past usage and pricing will be accurate. 
4. If the long-term statistics appear skewed and don't align with the dates - check the timezone settings of the underlying system/container. This is not an issue in HAOS. 

## Issues, bugs and new features

This type of integration is not easy to test. I only have my own account to test with, which has a very specfic setup. Your account setup is almost certainly different from mine, so if things don't work for you please open an issue and provide the following information:
- The supplier network you're connected to
- The type of meter you have - it's either a unified one (in that case on your power bill there's only one meter ending in `:1`) or a split one (in that case you'll see two meters there ending in `:1` and `:2`)
- Any logs you have from the integration

If you'd like to see some addtional features - please open an issue as well.

## Examples 

### Energy dashboard

This integration can be used to feed data into the Energy dashboard. In order to get it going configure the "Grid connection":

Energy imported from grid: `Power usage Statistics`  sensor.

Cost tracking: 
- Use entity tracking the total costs
- Select either `Nominal power cost Statistics` (for the "standard" rates)
- or `Effective power cost Statistics` (for the approximate effective rates)

![Energy dashboard](images/energy_dashboard.png)

### Hourly power usage statistics

The hourly consumption can be graphed using the standard "Statistics graph card" using the following `yaml` definition:
```
type: statistics-graph
grid_options:
  columns: full
entities:
  - entity: sensor:powershopnz_historical_usage_total
days_to_show: 4
period: hour
chart_type: bar
stat_types:
  - state
```

![Hourly usage](images/hourly_usage.png)

### Daily usage by rate type

The split in usage by rate type can be graphed using the "Statistics graph card" using the following `yaml` definition:
```
type: statistics-graph
grid_options:
  columns: full
entities:
  - sensor:powershopnz_historical_usage_all_weekend_off_peak
  - sensor:powershopnz_historical_usage_weekday_peak
  - sensor:powershopnz_historical_usage_weekday_off_peak
days_to_show: 50
period: day
chart_type: bar-stack
stat_types:
  - change
```
What's worth noting is that for this graph to work the `stat_type` must be set to `change` and not `state`. That applies to any graph that displays days (or more) of data at once.

![Daily by rate](images/usage_by_rate.png)

### Comparing effective and nominal daily costs

The nominal and effective daily costs can be compared on a single graph using the "Statistics graph card" using the following `yaml` definition:
```
type: statistics-graph
grid_options:
  columns: full
entities:
  - sensor:powershopnz_historical_nominal_cost_total
  - sensor:powershopnz_historical_effective_cost_total
days_to_show: 35
period: day
chart_type: bar
stat_types:
  - change
```

![Rate comparison](images/rate_comparison.png)

### Monthly summary by rate type

Monthly summary by rate type can be created using the "Statistics graph card" and the following `yaml` definition: 

```
type: statistics-graph
grid_options:
  columns: 24
  rows: auto
entities:
  - sensor:powershopnz_historical_usage_all_weekend_off_peak
  - sensor:powershopnz_historical_usage_weekday_off_peak
  - sensor:powershopnz_historical_usage_weekday_peak
days_to_show: 365
period: month
chart_type: bar-stack
stat_types:
  - change
```
![Monthly by rate](images/monthly_by_rate.png)

The actual names of the sensors are dynamically generated based on what the Powershop API returns for your account, so the names might be different.

### List of powerpacks that were used to achieve the discounted rate

The list can be extracted using the "Markdown" card and the following `yaml` definition:
```
type: markdown
content: |
  ## Powerpacks used

  {{ state_attr(
       'sensor.powershopnz_billing_period_cost_total_effective',
       'powerpacks'
     ) }}
grid_options:
  columns: 12
  rows: auto
```

![Powerpacks](images/powerpacks.png)

## Releases

### v1.0.11
- fixed a bug when in some circumstance the ratio can drop to 0 if there's no data for 2 days.


### v1.0.10
- added logo (still doesn't work due to a bug in HACS)

### v1.0.9
- futher improvments to the logic handling switchover between the billing cycles

### v1.0.8
- improved handling of the first day of the billing cycle, now it returns the previous day effective ratio, unless it's also unknown, in which case 1 is returned as the ratio


### v1.0.7
- fixed a bug, where the current effective rates were using first day of the billing cycle, not the current month rates

### v1.0.6
- improve handling of powerpack purchases
- fixed a bug when a powerpack was allocated to a day using UTC timezone

### v1.0.5
- moved away from a flat directory structure into custom_components

### v1.0.4
- Add expiry of old data
- Made re-auth flow functional
- Fixed powerpacks storing and processing logic

### v1.0.2 and v1.0.3
- Fixed of an initial crash when starting fresh
- Fixed to timezone skew for long term statistics when running on HAOS

### v1.0.0
- First release


## Acknowledgements 

This integration uses the [Historical sensor](https://github.com/ldotlopez/ha-historical-sensor) by Luis López. 
##  License

This project is licensed under the GPL License - see the [LICENSE](LICENSE) file for details.

