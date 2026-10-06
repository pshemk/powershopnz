## Releases


### v1.0.14
- fixed a bug where in some circumstances the billing dates would show as 'unknown' 

### v1.0.13
- use historical sensor to do all the filtering of data during the updates
- documentation updates

### v1.0.12
- further improvements to handling of powerpacks during billing cycles switchover

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


