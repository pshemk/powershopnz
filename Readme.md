# Powershop NZ — Home Assistant Integration

A Home Assistant custom integration that pulls data from your Powershop New Zealand account. 

##  Disclaimer

This is not an official integration provided by Powershop NZ. It simmply uses their API to extract the data. 

## Features

### Current price sensors

A sensor that reports the current price of a kWh. In addition to the nominal price there's also an effective price sensor that takes into consideration all the purchased (and available) powerpacks. These sensors can be used to provide price information to the Dynamic Energy Cost integration.

### Current rate type sensor

A sensor that reports the current rate type  (peak, off-peak, or any other returned by the Powershop API). This sensor can be used to trigger automations during lower-cost periods. Its worth noting that there might be multiple rates to cover the same type of tariff. For example, my own home connection has two rates: All Weekend Off Peak and Weekday Off Peak that are priced the same. This integration doesn't combine them, so if you need a simple peak/off-peak switch - use a template sensor that checks the current value of this sensor and report accordingly. 

### Side-loading of historical information

Past power usage and costs are available to Home Assistant as statistics. That means that the historical information can be used to populate the fantastic Energy Dashboard. 

### Highly customisable

Sensors can be disabled vie the options menu.

## Sensors

The integration provides the following regular sensors. All entities are in the `sensor.` domain.

| Name | Entity | Description | Unit | Update freqency|
|------|--------|-------------|------|-------------|
| Billing period cost: Effective Total |  `powershopnz_billing_period_cost_total_effective` | The cost of electricity in current billing period including powerpacks discounts | NZD | 10 mins | 
| Billing period cost: Nominal Total | `powershopnz_billing_period_cost_total_nominal` | The cost of electricity in current billing period using nominal pricing | NZD | 10 mins | 
| Billing period days so far | `powershopnz_billing_period_usage_daily_charge` | Number of days in the billing period with usage data so far | days | 10 mins | 
| Billing period usage: Total | `powershopnz_billing_period_usage_total` | Total power usage in the current billing period | kWh | 10 mins | 
| Billing period usage: Rate name | `powershopnz_billing_period_usage_[*rate_name*]` | Total power usage in the current  billing period during given rate period | kWh | 10 mins | 
| Current billing period start date | `powershopnz_current_billing_period_start_date` | The first timestamp of the current billing period | date-time | 5 mins | 
| Current billing period end date | `powershopnz_current_billing_period_end_date` | The last timestamp of the current biilling period | date-time | 5 mins |
| Next billing date | `powershopnz_current_next_billing_date` | The first timestamp of the next billing period | date-time | 5 mins | 
| Current rate type | `powershopnz_unit_rate_type` | Current rate type (peak, off-peak, night, etc) | 30 sec | 
| Daily charge | `powershopnz_daily_charge` | Daily charge | NZD | 5 mins | 
| Effective cost ratio | `powershopnz_effective_cost_ratio` | The proportion of the nominal cost of the units of power including powerpacks discounts | no unit | 10 mins | 
| Effective rate | `powershopnz_effective_unit_cost` | The cost of units of power including powerpacks discounts at current time| NZD |  10 mins | 
| Effective rate: Rate name | `powershopnz_effective_unit_cost_[*rate_name*]` | The cost of units of power including powerpacks discounts during given rate period | NZD | 10 mins |
| Nominal rate | `powershopnz_nominal_unit_cost` | The cost of units of power using nominal pricing at current time| NZD | 5 mins | 
| Nominal rate: Rate name | `powershopnz_nominal_unit_cost_[*rate_name*]` | The cost of units of power using nominal pricing during given rate period | NZD | 5 mins | 
| Powerpacks: available balance | `powershopnz_powerpacks_available_balance` | The sum value of currently available powerpacks | NZD | 5 mins |
| Powerpacks: future balance | `powershopnz_powerpacks_future_balance` | The sum value of powerpacks that will be available in future | NZD | 5 mins |
| Previous billing period cost: Effective Total |  `powershopnz_prevoius_billing_period_cost_total_effective` | The cost of electricity in previous billing period including powerpacks discounts | NZD | 10 mins | 
| Previous billing period cost: Nominal Total | `powershopnz_previous_billing_period_cost_total_nominal` | The cost of electricity in previous billing period using nominal pricing | NZD | 10 mins | 
| Previous billing period usage: Total | `powershopnz_prevoius_billing_period_usage_total` | Total power usage in the previous billing period | kWh | 10 mins | 


In addition to the sensors above the following sensors are also created. They are used to store the historical values based on usage pulled using the API. Since the API doesn't return current (or up to date) values these sensors always report their values as `unknown`, but they provide all the statistical values and can be used for graphing (or in the energy dashboard). The resolution of each sensor is 1h. Technically they only exist to provide a placeholder for the long-term statistics.

| Name | Entity | Description | Unit |
|------|--------|-------------|------|
| Power cost | `powershopnz_historical_cost_total` | The total cost of energy (using nominal rates) | NZD | 
|`Power cost Rate name | `powershopnz_historical_cost_[*rate_name*]` | The  cost of energy used during given rate period (using nominal rates) | NZD |
| Power usage | `powershopnz_historical_usage_total` | The total usage of energy | kWh | 
| Power usage Rate name | `powershopnz_historical_usage_[*rate_name*]` | The usage of energy  during given rate period | kWh |


## Notes

During the first run the integration attempts to download all available usage information. That might take a few minutes to complete. Only once the data has been downloaded the sensor values are be populated. 

The effective rates and costs are recaluated every time a powerpack is purchased or past usage information is made available by Powershop. That means that the rate fluctuates. Ultimately the "Billing Period: Effective Total" is still a much better estimation of what the actual cost at the end of the billing period will be than the nominal rates. 

The effective cost ratio is calculated only using the costs of units (kWh) of energy. The daily charge always remains unaffected by the ratio. 

All costs are calculated in the integration, so there might be some small differences when it comes to nominal costs due to rounding. It's done this way because downloading both costs and usage seems to be much slower than downloading the usage alone, also calulcating the costs in the integration make it easier to caluclate the discounted rates. 

The statistics are always with 1h resolution, but due to the way they're loaded (using the historical sensor) they don't behave exactly the same way regular sensors do. Please have a look at the examples. 

The billing period always rolls over into the next one before all data is available (powerpacks are "consumed" on the last day of the billing cycle when there's still no usage information). The billing period data then become available in the 'Previous billing' sensors. 

## Known issues

1. Switching between rates (peak/off-peak) doesn't happen at exact times. The integration updates the sensor with the current rate type every 30 seconds. 
2. Historical data that's loaded into statistics (like past power usage or past cost) can not be updated once stored. Since Powershop doesn't always release past usage information in chronological order newer data always blocks older data from being stored, that leads to gaps in the statistcs. So far I have not found a user-friendly workaround. Deleting the integration does not delete the statistics from Home Assistant either. The only way to delete them right now is to delete them from the database directly. 
3. The past costs are only calucated starting from the month when the integartion was installed. This is because only current (i.e. this month's) rates are available thorugh the API. Once stored the rates are kept for future use
4. Past costs are calculated when the integration starts, but some of the data (like powerpacks already used in the past) is not available, so this number will not be accurate untill the whole billing period rolls over


## Examples 



### v1.0.0 (2026-09-25)
- First release

##  License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

