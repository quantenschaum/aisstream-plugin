import os
import sys
import json
import pyais
import websocket
from time import monotonic, sleep
from math import radians, cos, copysign

from avnav_api import AVNApi

sys.path.insert(0, os.path.dirname(__file__))

SOURCE = "aisstream"
API_WS = "apiws"
API_KEY = "apikey"
DISTANCE = "distance"
CONFIG = [
    {
        "name": API_WS,
        "description": "websocket endpoint",
        "type": "STRING",
        "default": 'wss://stream.aisstream.io/v0/stream',
    },
    {
        "name": API_KEY,
        "description": "aisstream.io API key",
        "type": "STRING",
        "default": '',
    },
    {
        "name": DISTANCE,
        "description": "distance around own position to poll for AIS data",
        "type": "FLOAT",
        "default": 20,
    },
]


class Plugin(object):

    @classmethod
    def pluginInfo(cls):
        return {
            "description": "aisstream.io data source",
            "config": CONFIG,
            "data": [],
        }

    def __init__(self, api: AVNApi):
        self.api = api
        self.api.registerEditableParameters(CONFIG, self.changeParam)
        self.api.registerRestart(self.stop)
        self.seq = 0
        self.saveAllConfig()

    def stop(self):
        pass

    def getConfigValue(self, name):
        defaults = self.pluginInfo()["config"]
        for cf in defaults:
            if cf["name"] == name:
                return self.api.getConfigValue(name, cf.get("default"))
        return self.api.getConfigValue(name)

    def saveAllConfig(self):
        d = {}
        defaults = self.pluginInfo()["config"]
        for cf in defaults:
            v = self.getConfigValue(cf.get("name"))
            d.update({cf.get("name"): v})
        self.api.saveConfigValues(d)
        return

    def changeConfig(self, newValues):
        self.api.saveConfigValues(newValues)

    def changeParam(self, param):
        self.api.saveConfigValues(param)
        self.read_config()

    def read_config(self):
        config = {}
        for c in CONFIG:
            name = c["name"]
            TYPES = {"FLOAT": float, "NUMBER": int, "BOOLEAN": lambda s: s == "True"}
            value = self.getConfigValue(name)
            value = TYPES.get(c.get("type"), str)(value)
            config[name] = value
        self.config = config
        self.config_changed = True

    def readValue(self, path):
        "prevents reading values that we self have calculated"
        a = self.api.getSingleValue(path, includeInfo=True)
        # if a: print(path, a.value, a.source, a.priority / 10)
        if a is not None and SOURCE not in a.source:
            return a.value

    def run(self):
        self.api.log("started")
        self.read_config()
        self.api.setStatus("STARTED", "running")
        msg_count=0

        while not self.api.shouldStopMainThread():
            try:
                ws = websocket.WebSocket()
                r=ws.connect(self.config[API_WS],timeout=10)

                def request_msg():
                  if not self.config[API_KEY]:
                    raise Exception('no API key')
                  lat,lon = list(map(self.readValue,['gps.lat','gps.lon']))
                  if lat is None or lon is None:
                    raise Exception('no position')
                  dist=self.config[DISTANCE]
                  d=dist/60
                  nw = lat+d, lon+d/cos(radians(lat))
                  se = lat-d, lon-d/cos(radians(lat))
                  ws.send(json.dumps({
                    'APIKey': self.config[API_KEY],
                    'BoundingBoxes': [[nw,se]],
                    'FilterMessageTypes': ['PositionReport','ShipStaticData','AidsToNavigationReport'],
                  }))
                  self.t_req=monotonic()
                  self.api.setStatus("NMEA", f'listening at ({lat:.5f},{lon:.5f}) {dist}nm')

                request_msg()

                while not self.api.shouldStopMainThread():
                  try:
                    if monotonic()-self.t_req>300:
                      request_msg()
                    msg=ws.recv()
                    msg=json.loads(msg)
                    msg_count+=1
                    nmea=ais_encode(msg)
                    if nmea:
                      for s in nmea:
                        self.api.addNMEA(s,source=SOURCE,omitDecode=False)
                      self.api.setStatus("NMEA", f'processed {msg_count} messages')
                  except websocket.WebSocketTimeoutException as x:
                    pass
            except Exception as x:
                print('ERROR',x)
                sleep(10)
                self.api.setStatus("ERROR", f"{x}")
            finally:
                ws.close()

FIELDS = {
    # pyais : aisstream
    'msg_type':'MessageID',
    'mmsi':'UserID',
    'second':'Timestamp',
    'status':'NavigationalStatus',
    'lat':'Latitude',
    'lon':'Longitude',
    'heading':'TrueHeading',
    'maneuver':'SpecialManoeuvreIndicator',
    'course':'Cog',
    'speed':'Sog',
    'turn':'RateOfTurn',
    'imo':'ImoNumber',
    'callsign':'CallSign',
    'shipname':'Name',
    'destination':'Destination',
    'ship_type':'Type',
    'draught':'MaximumStaticDraught',
    'off_position':'OffPosition',
    'virtual_aid':'VirtualAtoN',
    'aid_type':'AtoN',
    'name':'Name',
    'raim':'Raim',
    'repeat':'RepeatIndicator',
    'valid':'Valid',
    'accuracy':'PositionAccuracy',
    # 'xxx':'FixType',
}

def ais_encode(msg):
  rpt=None
  if 'MessageType' not in msg: return

  if msg['MessageType']=='PositionReport':
    # {'Message': {'PositionReport': {'Cog': 360, 'CommunicationState': 59916, 'Latitude': 54.43129833333333, 'Longitude': 12.690098333333333, 'MessageID': 1, 'NavigationalStatus': 0, 'PositionAccuracy': True, 'Raim': True, 'RateOfTurn': -128, 'RepeatIndicator': 0, 'Sog': 0, 'Spare': 0, 'SpecialManoeuvreIndicator': 1, 'Timestamp': 18, 'TrueHeading': 511, 'UserID': 211771340, 'Valid': True}},
    rpt=msg['Message']['PositionReport']

  if msg['MessageType']=='ShipStaticData':
    # {'Message': {'ShipStaticData': {'AisVersion': 1, 'CallSign': 'PCGZ   ', 'Destination': 'FIUKI               ', 'Dimension': {'A': 124, 'B': 10, 'C': 7, 'D': 9}, 'Dte': False, 'Eta': {'Day': 1, 'Hour': 11, 'Minute': 0, 'Month': 1}, 'FixType': 1, 'ImoNumber': 9207508, 'MaximumStaticDraught': 4.7, 'MessageID': 5, 'Name': 'MISSISSIPPIBORG     ', 'RepeatIndicator': 0, 'Spare': False, 'Type': 70, 'UserID': 244976000, 'Valid': True}},
    rpt=msg['Message']['ShipStaticData']

  if msg['MessageType']=='AidsToNavigationReport':
    # {'Message': {'AidsToNavigationReport': {'AssignedMode': False, 'AtoN': 0, 'Dimension': {'A': 13, 'B': 13, 'C': 13, 'D': 13}, 'Fixtype': 7, 'Latitude': 54.85855, 'Longitude': 14.04712, 'MessageID': 21, 'Name': 'WK NW-11 WINDFARM', 'NameExtension': 'W=Q>)', 'OffPosition': False, 'PositionAccuracy': True, 'Raim': False, 'RepeatIndicator': 3, 'Spare': False, 'Timestamp': 44, 'Type': 3, 'UserID': 992111887, 'Valid': True, 'VirtualAtoN': False}},
    rpt=msg['Message']['AidsToNavigationReport']

  if rpt:
    data={k:rpt[v].strip() if isinstance(rpt[v],str) else rpt[v] for k,v in FIELDS.items() if v in rpt}
    if 'turn' in data:
      rot=data['turn']
      if abs(rot)<127:
        data['turn'] = copysign((rot/4.733)**2,rot)
      else:
        del data['turn']
    if 'speed' in data and data['speed']>=102.3:
      del data['speed']
    if 'Dimension' in rpt:
      data['to_bow']=rpt['Dimension']['A']
      data['to_stern']=rpt['Dimension']['B']
      data['to_port']=rpt['Dimension']['C']
      data['to_starboard']=rpt['Dimension']['D']

    nmea=pyais.encode_dict(data, talker_id="AIVDM")

    # print(rpt)
    # print(data)
    # print(nmea)
    # # print(pyais.decode(nmea[0]))
    # print(100*'-')

    return nmea

