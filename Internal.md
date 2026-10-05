# The inner workings of this integration

## Architecture

This integration is made up of a number of components (it follows a cloud polling HA model):

```
                                          ------------------
                                          |                |
                                          |     Store      |
                                          |                |
                                          ------------------                                                
                                                  ^
                                                  | 
                                                  | read/write
                                                  |
                                                  ⌄

   ------------------                     ------------------                  ------------------
   |                |                     |                |                  |                | 
   |    Sensor      |  -- gets data --->  |  Cooridnator   | -- gets data --> | Powershop API  | 
   |                |              ---->  |                |                  |                |
   ------------------              |      ------------------                  ------------------ 
                                   |   
            ------ gets data -------
            |
   ------------------                     ------------------ 
   |   Historical   |                     |                | 
   |    Sensor      | -- statistics --->  |    Recorder    | 
   |                |                     |                | 
   ------------------                     ------------------ 
```

The `Cooridnator` is the key component here, it's responsible for:
- polling the Powershop API (using the API library)
   - getting rates, schedules, billing dates, etc
   - periodically checking the powerpacks values
   - periodically checking for past usage
- updating the current rate type (based on the previously calculated schedule)
- analysing past usage
- calculating the costs (including powerpacks discounts)
- storing the data in a local `HA Store` (which is effectively a number of `json` files inside `/config/.storage` directory)

The `Sensor` is registered with `HA` during initalisation. It's only function is to return a current value specific to the sensor key from the `Coordinator` (a few sensors also return addditional attributes using the exactly the same mechanism)

The `Historical Sensor` is also registred with `HA` during intialisation, but it doesn't have any current value method. Instead it periodically checks the coordinator for any new past data, and if found - they get stored in the `Recorder` (which is effectively a database) as long-term statistics. 

The `Store` is a simple `json` serialiser/deserialiser. It's used for preserving data during the restarts of `HA` and also to limit what needs to pulled from the Powershop API. It stores the following data:
- powerpacks balances (any change to those triggers a more thorough refersh of the state of the `Coordinator`)
- rate schedules (peak/off-peak/night/etc), they get refreshed once a day
- nominal pricing (unit costs and daily costs), the pricing is storead for each month
- powerpacks, the list of powerpacks is stored for each day
- usage, past usage in (almost) raw form from Powershop API, in 30mins intervals
- calculated values of various sensors:
  - historical sensors (usage, usage by rate, cost)
  - regular sensors (billing periods costs/dates/usage, effective unit costs and ratios)
  - attributes for powerpack-related sensors
- current "state" of the integration - i.e. what data has been procecessed, when was the last time particular functions ran

## Coordinator

The `Coordinator` is responsible for the initialisation of the integration. It sets up (or reads) the stores and launches internal tasks:
- fetching of the usage data (on launch and every 10 minutes, this runs in the background)
- processing of the usage data (on launch only)
- exipry of old data (older than two bililng cycles, on launch and every 6h)

`HA` calls the `_async_update_data` method every 30 seconds. That method is responsible for returning all of the sensors values. They are either calculated on the spot, or extracted from the "sensors" store. If it's been more than 5 minutes since the last API call - the API is called to check for the current powerpacks balances. If the balances have changed that can mean one of the following:
 * a new powerpack has been purchased 
 * a billing period has been closed (and powerpacks have been consumed)
 * a month has rolled over (and some "future" powerpacks became available)

 All these circumstances, and when new usage data is receeived - a complete recalculation of all data is triggered (this is a background task)
 In addition, during the first pull of the day the rates and rates schedules are also refreshed. 

 ## Historical data

 Historical data is loaded directly into the recorder/long term statistics using the [Historical sensor](https://github.com/ldotlopez/ha-historical-sensor). That means that even when the integration is removed the data stays in the database. The data is keyed of the names of the sensors. Beacause of the way the recoder works only newer data than what's currently stored can be added. Ocassionally Powershop returns data in non-linear order, when later dates already have usage data, even though some previous ones dont, in that case the process below is the only way to insert the missing data.

 ### Removing data from the recorder

 These steps need to be carried out directly on the `HA` internal database. By default it's stored in `/config` directory as `home-assistant_v2.db`. 

 In order to remove the data the `id` from `statistics` table is needed:

 ```
 sqlite> select id, statistic_id, name  from statistics_meta where statistic_id like '%powershopnz_historical%';
40|sensor:powershopnz_historical_usage_total|Power usage Statistics
41|sensor:powershopnz_historical_cost_total|Power cost Statistics
42|sensor:powershopnz_historical_usage_weekday_peak|Power usage Weekday Peak Statistics
43|sensor:powershopnz_historical_cost_weekday_off_peak|Power cost Weekday Off Peak Statistics
44|sensor:powershopnz_historical_cost_all_weekend_off_peak|Power cost All Weekend Off Peak Statistics
45|sensor:powershopnz_historical_cost_weekday_peak|Power cost Weekday Peak Statistics
46|sensor:powershopnz_historical_usage_weekday_off_peak|Power usage Weekday Off Peak Statistics
47|sensor:powershopnz_historical_usage_all_weekend_off_peak|Power usage All Weekend Off Peak Statistics
54|sensor:powershopnz_historical_nominal_cost_total|Nominal power cost Statistics
55|sensor:powershopnz_historical_nominal_cost_weekday_off_peak|Nominal poower cost Weekday Off Peak Statistics
56|sensor:powershopnz_historical_nominal_cost_all_weekend_off_peak|Nominal poower cost All Weekend Off Peak Statistics
57|sensor:powershopnz_historical_nominal_cost_weekday_peak|Nominal poower cost Weekday Peak Statistics
58|sensor:powershopnz_historical_effective_cost_total|Effective power cost Statistics
```

(the `id` is in the first column above)

Those `id`s can be then used to delete the values from the database:
```
sqlite> delete from statistics where metadata_id in (40,41,42,43,44,45,45,46,47,54, 55,56,57,58);
```

Once the `HA` is restarted (or the integration, via the settings menu and the `Reprocess current billing period` option) the data will be re-populated. 


