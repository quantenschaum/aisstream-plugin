#!/usr/bin/env python3

import os
import sys
import json
import pyais
import socket
import select
import websocket
from time import monotonic, sleep
from math import radians, cos, copysign

if __name__!='__main__':
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

    def __init__(self, api):
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
                    'FilterMessageTypes': [
                      'PositionReport',
                      'StandardClassBPositionReport',
                      'ExtendedClassBPositionReport',
                      'ShipStaticData',
                      'StaticDataReport',
                      'AidsToNavigationReport'
                      ],
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
  # print(msg)
  type=msg.get('MessageType')
  if not type: return
  rpt=msg['Message'].get(type)
  if not rpt: return

  name=msg['MetaData'].get('ShipName')
  mmsi=msg['MetaData'].get('MMSI')

  rpt.update(rpt.get('ReportA',{}))
  rpt.update(rpt.get('ReportB',{}))
  # rpt.update({'ShipName':name,'Name':name,'UserID':mmsi})

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

  # print(type,mmsi,name)
  # for k,v in rpt.items():
  #   print(' ' if k in FIELDS.values() else '!',k,v)
  # print('data')
  # for k,v in data.items():
  #     print(' ',k,v)
  #
  # print(nmea)
  # # print(pyais.decode(nmea[0]))
  # print(100*'-')

  return nmea


class UDPBroadcaster:
  def __init__(self, addr, port):
    self.addr=addr or '<broadcast>'
    self.port=port
    self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    if 'broadcast' in self.addr:
      self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    self.socket.settimeout(1)

  def close(self):
    self.socket.close()

  def serve(self, message):
    self.socket.sendto(message.encode(), (self.addr, self.port))


class TCPServer:
  def __init__(self, addr, port):
    # self.send = send
    # self.receive = receive
    if socket.has_dualstack_ipv6():
      self.server = socket.create_server((addr, port), family=socket.AF_INET6, dualstack_ipv6=True)
    else:
      self.server = socket.create_server((addr, port))

    self.conns = []

  def close(self):
      self.server.close()

  def serve(self, data_to_send, received=lambda d: d):
    try:
      rx, tx, er = select.select([self.server], [], [self.server], 0)
      # print("server", rx, tx, er)
      for so in rx:
        conn, addr = so.accept()
        print("accepted", conn, file=sys.stderr)
        conn.setblocking(False)
        self.conns.append(conn)

      if not self.conns:
        return

      rx, tx, er = select.select(self.conns, self.conns, self.conns, 0)
      # print("connections", rx, tx, er)

      if tx:
        # data = self.send()
        # print(data_to_send, file=sys.stderr)
        for co in tx:
          try:
            # print("TX", co)
            co.send(data_to_send.encode())
            # print(data, file=sys.stderr)
          except Exception as x:
            print(x, co, file=sys.stderr)
            self.conns.remove(co)

      for co in rx:
        try:
          # print("RX", co)
          data = co.recv(4096).decode()
          if data:
            # print(data, file=sys.stderr)
            # self.receive(data)
            received(data)
        except Exception as x:
          print(x, co, file=sys.stderr)
          sleep(3)
          self.conns.remove(co)

      for co in er:
        print("ERROR", co, file=sys.stderr)
        sleep(3)
        self.conns.remove(co)

    except Exception as x:
      print(x, file=sys.stderr)
      sleep(3)


if __name__=='__main__':
    from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter

    parser = ArgumentParser(description='ais-stream NMEA server', formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument('lat',help='latitude in degrees',type=float)
    parser.add_argument('lon',help='longitude in degrees',type=float)
    parser.add_argument('radius',help='radius around position in nm',type=float)
    parser.add_argument('-k','--apikey')
    parser.add_argument('-w','--wsocket',default='wss://stream.aisstream.io/v0/stream')
    parser.add_argument('-a','--addr',help='server address',default='')
    parser.add_argument('-p','--port',help='server port',type=int,default=10110)
    parser.add_argument('-u','--udp',help='broadcast UDP to addr and port',action='store_true')
    parser.add_argument('-v','--verbose',help='print AIS messages',action='count',default=0)
    args=parser.parse_args()


    while True:
        try:
            ws = websocket.WebSocket()
            ws.connect(args.wsocket,timeout=10)

            if args.udp:
              s=UDPBroadcaster(args.addr, args.port)
            else:
              s=TCPServer(args.addr, args.port)

            def request_msg():
              lat,lon = args.lat, args.lon
              d=args.radius/60
              nw = lat+d, lon+d/cos(radians(lat))
              se = lat-d, lon-d/cos(radians(lat))
              ws.send(json.dumps({
                'APIKey': args.apikey,
                'BoundingBoxes': [[nw,se]],
                'FilterMessageTypes': ['PositionReport','ShipStaticData','AidsToNavigationReport'],
              }))

            request_msg()

            while True:
              try:
                msg=ws.recv()
                msg=json.loads(msg)
                if args.verbose>0 or 'error' in msg: print(msg)
                if 'Message' in msg:
                  nmea=ais_encode(msg)
                  if args.verbose>1: print(nmea)
                  for sentence in nmea: s.serve(sentence+'\n')
              except websocket.WebSocketTimeoutException as x:
                pass
        except Exception as x:
            print('ERROR',x)
            sleep(10)
        finally:
            ws.close()
            s.close()
