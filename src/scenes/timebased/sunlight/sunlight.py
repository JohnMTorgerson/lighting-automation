import os
from dotenv import load_dotenv
from pprint import pprint
import datetime
from suntime import Sun, SunTimeException
import math

try:
    from zoneinfo import ZoneInfo
except:
    from backports.zoneinfo import ZoneInfo

# import wyze_sdk
# wyze_sdk.set_file_logger(__name__, 'tmp/log.log')

import logging
# create logger
sunlight_logger = logging.getLogger(f"main.{__name__}")
# sunlight_logger = logging.getLogger(__name__)

try:
    load_dotenv()
    latitude = float(os.environ['LAT'])
    longitude = float(os.environ['LON'])
except Exception as e:
    sunlight_logger.error(f"Error: could not load latitude and longitude from environment: {e}")


def run(client=None,bulbs=[],bulb_props={},now=None,log=True) :
    # if log=False is passed, we don't want to do any logging, so set to a null handler
    if log == False :
        # set sunlight_logger to null handler
        global sunlight_logger
        sunlight_logger = logging.getLogger("null")
    else :
        # otherwise, we have to reset to the actual logger (in case False was passed previously)
        # this is clearly not the best way to handle this, but it'll work for now
        # probably this whole project needs to be re-written using classes
        sunlight_logger = logging.getLogger(f"main.{__name__}")

    sunlight_logger.info('Running sunlight scene...')

    if len(bulbs) > 0 and client is None or isinstance(client,list) :
        err = 'Must pass client object to sunlight.run()'
        sunlight_logger.critical(err)
        raise Exception(err)
        # pass

    minutes_since = get_relative_time(now)

    if minutes_since is not None:

        srt = minutes_since['sunrise']
        sst = minutes_since['sunset']
        # nearest_event_time = srt if abs(srt) < abs(sst) else sst

        # defaults in case of error
        temp = 2700
        brightness = 100


        # ======================= CRAP FOR LOGGING ONLY =============================
        # These baseline values are only calculated for logging purposes;
        # we calculate the actual values used per bulb in the for loop below;
        # (there may be per-bulb adjustments for time, and then also for temp and brightness in addition)
        try :
            temp_baseline = round(get_temp(srt,sst),2)
            brightness_baseline = round(get_brightness(srt,sst),2)
        except Exception as e:
            sunlight_logger.error(e)
            raise e
        sunlight_logger.info(f"BASELINE VALUES ==== sunrise: {int(srt)}, sunset: {int(sst)}, temp: {temp_baseline}, brightness: {brightness_baseline}")

        # just to prettify the logging
        max_name_length = 0
        for bulb in bulbs :
            name_length = len(bulb.nickname)
            if name_length > max_name_length :
                max_name_length = name_length

        # ^^===================== /CRAP FOR LOGGING ONLY ===========================^^

        for bulb in bulbs:

            # GET TIME ADJUSTMENT PER BULB (IF GIVEN), TO APPLY TO ALL SUBSEQUENT PER-BULB ADJUSTMENTS (IF GIVEN)
            try:
                adjusted_srt = bulb_props.bulbs[bulb.nickname]['srt_adjust'](srt)
            except:
                adjusted_srt = srt
            try:
                adjusted_sst = bulb_props.bulbs[bulb.nickname]['sst_adjust'](sst)
            except:
                adjusted_sst = sst

            temp = get_temp(adjusted_srt,adjusted_sst)
            brightness = get_brightness(adjusted_srt,adjusted_sst)

            # GET ADJUSTED TEMP
            try:
                adjusted_temp = bulb_props.bulbs[bulb.nickname]["temp_adjust"](temp)
            except:
                sunlight_logger.warning(f"Could not find adjusted temp for {bulb.nickname}")
                adjusted_temp = temp

            # GET ADJUSTED BRIGHTNESS
            try:
                adjusted_brightness = bulb_props.bulbs[bulb.nickname]["brightness_adjust"](brightness,adjusted_temp)
            except:
                sunlight_logger.warning(f"Could not find adjusted brightness for {bulb.nickname}")
                adjusted_brightness = brightness

            # GET ON/OFF ADJUSTMENT
            try:
                turn_on = bulb_props.bulbs[bulb.nickname]["on_adjust"](adjusted_brightness)
            except:
                sunlight_logger.debug(f"Could not find on_adjust from bulb_props for {bulb.nickname}, so leaving on")
                turn_on = True

            # round the values to nearest integer before sending to API
            adjusted_temp = round(adjusted_temp)
            adjusted_brightness = round(adjusted_brightness)

            # sunlight_logger.debug(f"{bulb.nickname}: temp={adjusted_temp}, brightness={adjusted_brightness}, on={turn_on}")

            # SEE IF BULB IS ACTUALLY ON OR OFF ALREADY
            try:
                is_on = client.bulbs.info(device_mac=bulb.mac).is_on
            except:
                sunlight_logger.warning(f"Could not find on/off state for {bulb.nickname}")
                is_on = False

            # SET ALL THE VALUES WE JUST GOT
            if turn_on is True:
                # if turn_on is true, any adjustments we make will turn the bulb on if it's off,
                # so all we need to do is make the adjustments
                # sunlight_logger.debug('on is True')
                # client.bulbs.turn_on(device_mac=bulb.mac, device_model=bulb.product.model)
                client.bulbs.set_color_temp(device_mac=bulb.mac, device_model=bulb.product.model, color_temp=adjusted_temp)
                client.bulbs.set_brightness(device_mac=bulb.mac, device_model=bulb.product.model, brightness=adjusted_brightness)
            elif turn_on is False and is_on:
                # if turn_on is false and the bulb is actually on, then we need to manually turn it off
                # sunlight_logger.debug('on is False and bulb.is_on')
                client.bulbs.turn_off(device_mac=bulb.mac, device_model=bulb.product.model)

            num_spaces = max_name_length - len(bulb.nickname)
            spaces = " " * num_spaces

            sunlight_logger.info(f"{bulb.nickname}{spaces} (adjusted values) --- sunrise: {int(adjusted_srt)}, sunset: {int(adjusted_sst)}, temp: {adjusted_temp}, brightness: {adjusted_brightness}, turn_on={turn_on}, is_on={is_on}")


    else:
        sunlight_logger.error("Could not get sunrise/sunset times")


    # for n in range(int(1621054800/60/30),int(1621141200/60/30)):
    #     time = datetime.datetime.fromtimestamp(n*30*60)
    #     times = get_relative_time(time)
    #     get_temp(times['sunrise'],times['sunset'])

    # the return value is not used for anything during the normal running of the script;
    # but it is used for creating json data of the whole values curve, which is referenced by the automation GUI
    return [temp_baseline,brightness_baseline]


def get_brightness(srt,sst) :
    args = {
        'low': 40,
        'high': 120, # the maximum is 100, but we can make this higher as long as ceiling <= 100
        'floor': 50,
        'ceiling': 100,
        'steepness': 1/60, # unitless constant to adjust the steepness of the curve
        'offset': 45, # positive offset makes changes happen later (in minutes). If 0, the steepest part of the curve will be right at sunrise/sunset
    }

    b = 100 # just a default in case all the conditionals fail for some reason

    # MIDNIGHT TO SUNRISE
    if srt < 0:
        # print("MIDNIGHT TO SUNRISE")
        args['time'] = srt
        args['direction'] = 'ascending'
        b = values_curve(args)

    # SUNRISE TO MIDDAY
    elif srt >= 0 and sst < 0 and abs(srt) < abs(sst):
        # print("SUNRISE TO MIDDAY")
        b = 100

    # MIDDAY to SUNSET
    elif srt > 0 and sst < 0 and abs(srt) >= abs(sst):
        # print("MIDDAY to SUNSET")
        args['time'] = sst
        args['direction'] = 'descending'
        b = values_curve(args)

    # SUNSET TO MIDNIGHT
    elif srt > 0 and sst >= 0:
        # print("SUNSET TO MIDNIGHT")
        args['time'] = sst
        args['direction'] = 'descending'
        b = values_curve(args)

    return b

def get_temp(srt,sst) :
    # sst is minutes since sunrise (so, negative if before sunrise)
    # sst is minutes since sunset (so, negative if before sunset)
    warmest = 2400
    coldest = 5900

    args = {
        'low': warmest, # 1800 is the minimum possible value for mesh bulbs
        'high': coldest, # 6500 is the maximum possible value for mesh bulbs
        'floor': warmest + 100,
        'ceiling': coldest - 100,
        'steepness': 1/20, # unitless constant to adjust the steepness of the curve
        'offset': -20 # positive offset makes changes happen later (in minutes). If 0, the steepest part of the curve will be right at sunrise/sunset
    }

    temp = 2700 # just a default in case all the conditionals fail for some reason


    if coldest < warmest:
        raise Exception('warmest temp must be a smaller value than coldest temp')

    # MIDNIGHT TO SUNRISE
    if srt < 0:
        sunlight_logger.debug("MIDNIGHT TO SUNRISE")
        # temp = values_curve(time=srt,offset=offset,low=warmest,high=coldest,steepness=steepness,direction='ascending',floor=floor,ceiling=ceiling)
        args['time'] = srt
        args['direction'] = 'ascending'
        temp = values_curve(args)

    # SUNRISE TO MIDDAY
    elif srt >= 0 and sst < 0 and abs(srt) < abs(sst):
        sunlight_logger.debug("SUNRISE TO MIDDAY")
        # temp = values_curve(time=srt,offset=offset,low=warmest,high=coldest,steepness=steepness,direction='ascending',floor=floor,ceiling=ceiling)
        args['time'] = srt
        args['direction'] = 'ascending'
        temp = values_curve(args)

    # MIDDAY to SUNSET
    elif srt > 0 and sst < 0 and abs(srt) >= abs(sst):
        sunlight_logger.debug("MIDDAY to SUNSET")
        # temp = values_curve(time=sst,offset=offset,low=warmest,high=coldest,steepness=steepness,direction='descending',floor=floor,ceiling=ceiling)
        args['time'] = sst
        args['direction'] = 'descending'
        temp = values_curve(args)

    # SUNSET TO MIDNIGHT
    elif srt > 0 and sst >= 0:
        sunlight_logger.debug("SUNSET TO MIDNIGHT")
        # temp = values_curve(time=sst,offset=offset,low=warmest,high=coldest,steepness=steepness,direction='descending',floor=floor,ceiling=ceiling)
        args['time'] = sst
        args['direction'] = 'descending'
        temp = values_curve(args)

    # temp = range * math.atan((offset - time) * steepness)/math.pi + warmest + range/2

    return temp

def values_curve(args):
    '''
    Create a value (e.g. temp or brightness) based on the arctan of a given time input; arctan is used in order to generate a smooth curve between high and low horizontal asymptotes

    :param dict args: can contain any of the following properties:

        int time: the time (in minutes) since event, i.e. sunrise/sunset (so, time is negative if event is in the future)
        int offset: slide the curve earlier or later relative to time_anchor; positive offset makes changes happen later (in minutes)
        int low: the lower asymptote limit
        int high: the upper asymptote limit
        float floor: an optional hard minimum, clipping the lower asymptote limit
        float ceiling: an optional hard maximum, clipping the upper asymptote limit
        float steepness: a unitless constant to adjust the steepness of the curve
        str direction: should be either 'descending' or 'ascending', adjusts direction of curve

    :return: the value (e.g. temp or brightness)
    :rtype: int

    :raises ValueError: if low > high
    :raises ValueError: if floor > ceiling
    '''

    defaults = {
        'time':0,
        'offset':0,
        'low':0,
        'high':100,
        'steepness':1/15,
        'direction':'descending',
        'floor':float('-inf'),
        'ceiling':float('inf')
    }

    args = {**defaults, **args}

    range = args['high'] - args['low']
    if range < 0:
        raise ValueError('Error: min (warmest temp or lowest brightness) must be a smaller value than max (coolest temp or highest brightness)')

    if args['floor'] > args['ceiling']:
        raise ValueError('Error: floor must be less than or equal to ceiling')

    if args['direction'] != 'ascending' and args['direction'] != 'descending':
        raise ValueError("Error: direction must be either 'ascending' or 'descending'")

    direction = 1 if args['direction'] == 'descending' else -1

    return min(args['ceiling'],max(args['floor'],direction * range * math.atan((args['offset'] - args['time']) * args['steepness'])/math.pi + args['low'] + range/2))

def get_relative_time(now=datetime.datetime.now(tz=ZoneInfo('US/Central'))):
    try :
        sun = Sun(latitude, longitude)

        # now = datetime.datetime(2022, 3, 14, 20, 15, 0)
        # now = now + datetime.timedelta(1)
        today = now.date() # just used for debugging/logging
        sunlight_logger.debug(f"Now: {now}")

        sunrise = sun.get_local_sunrise_time(now)#.replace(tzinfo=ZoneInfo('US/Central'))
        sunlight_logger.debug(f"Sunrise: {sunrise}")
        # sunset = sun.get_local_sunset_time(now).replace(tzinfo=pytz.utc).astimezone(pytz.timezone('America/Chicago'))
        # sunset = sun.get_local_sunset_time(now).replace(tzinfo=datetime.timezone.utc).astimezone(ZoneInfo('US/Central'))
        sunset = sun.get_local_sunset_time(now)
        # bug workaround:
        if sunset < sunrise:
            sunset = sunset + datetime.timedelta(1)
        sunlight_logger.debug(f"Sunset: {sunset}")
        sunlight_logger.debug('On {} the sun rose at {} and set at {}.'.
              format(today, sunrise.strftime('%H:%M'), sunset.strftime('%H:%M')))

        # delta = datetime.timedelta(hours=1)
        sr_delta = (now.timestamp() - sunrise.timestamp()) / 60 # number of minutes since sunrise
        ss_delta = (now.timestamp() - sunset.timestamp()) / 60 # number of minutes since sunset
        sunlight_logger.debug(f"Sunrise was {int(sr_delta / 6) / 10} hours ago")
        sunlight_logger.debug(f"Sunset was {int(ss_delta / 6) / 10} hours ago")

        data = {
            "sunrise": sr_delta,
            "sunset": ss_delta,
            "sunrise_abs": sunrise,
            "sunset_abs": sunset
        }

    except SunTimeException as e:
        sunlight_logger.error(f"Problem getting sunrise/sunset times: {e}")
    else:
        return data

if __name__ == "__main__" :
    run()
