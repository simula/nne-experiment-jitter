#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =================================================================
#          #     #                 #     #
#          ##    #   ####   #####  ##    #  ######   #####
#          # #   #  #    #  #    # # #   #  #          #
#          #  #  #  #    #  #    # #  #  #  #####      #
#          #   # #  #    #  #####  #   # #  #          #
#          #    ##  #    #  #   #  #    ##  #          #
#          #     #   ####   #    # #     #  ######     #
#
#       ---   The NorNet Testbed for Multi-Homed Systems  ---
#                       https://www.nntb.no
# =================================================================
#
# Container-based UDPPing for NorNet Edge
#
# Copyright (C) 2018 by Thomas Dreibholz
# Copyright (C) 2012-2017 by Džiugas Baltrūnas
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Contact: dreibh@simula.no


# Ubuntu/Debian dependencies:
# python3-netifaces

import argparse
import datetime
import logging
import logging.config
import netifaces
import os
import re
import signal
import socket
import sys
import threading
import time
from ipaddress import ip_address


# ###### Constants ##########################################################
RTT_VALID_MIN   = 0      # Minimum valid RTT (in s)
RTT_VALID_MAX   = 300    # Maximum valid RTT (in s)
PAYLOAD_MAX     = 2048   # Maximum payload size (in B)
SLEEP_ON_ERROR  = 15     # Waiting time before restarting on error (in s)

DEFAULT_DADDR   = ip_address('128.39.37.70')   # Default Ping destination with UDP Echo (voyager.nntb.no)
DEFAULT_DPORT   = 7      # Default destination port
DEFAULT_PSIZE   = 20     # Default payload size
DEFAULT_TIMEOUT = 60     # Default reply timeout (in s)

LOG_DIRECTORY   = '/monroe/results/log'
DATA_DIRECTORY  = '/monroe/results/data'


# ###### Global variables ###################################################
running = True
restart = False


# ###### Signal handler #####################################################
def handler(signum, frame):
   global running
   running = False


# ###### Receiver thread ####################################################
class Receiver(threading.Thread):
   # ###### Constructor #####################################################
   def __init__(self, udpSocket, lock, requests, timeout):
      threading.Thread.__init__(self)
      self.udpSocket = udpSocket
      self.udpSocket.settimeout(1)
      self.lock      = lock
      self.requests  = requests
      self.timeout   = timeout
      self.daemon    = True
      self.terminate = threading.Event()

   # ###### Main loop #######################################################
   def run(self):
      global running, restart
      logging.info("Starting receiver thread")

      # ====== Reception loop ===============================================
      while running and not self.terminate.is_set():
         payload = None
         try:
            # ====== Receive response =======================================
            payload          = self.udpSocket.recv(PAYLOAD_MAX)
            receiveTimeStamp = time.time()   # time stamp in s

            # ====== Get RTT ================================================
            [seqNumber, sendTimeStamp] = payload.decode('utf-8').strip().split(' ')
            sendTimeStamp = int(sendTimeStamp) / 1000000.0   # time stamp in s
            rtt = receiveTimeStamp - sendTimeStamp
            if not ((rtt >= RTT_VALID_MIN) and (rtt <= RTT_VALID_MAX)):
               logging.warn("Invalid RTT: %s", payload)
               continue
            sendTimeStampString = \
               datetime.datetime.utcfromtimestamp(sendTimeStamp).strftime('%Y-%m-%d %H:%M:%S.%f')

            # ====== Check for duplicate or expired =========================
            if payload in self.requests:
               e = 0
            else:
               e = 1
               logging.warn("Duplicate or expired, seqNumber=%d sendTimeStampString=%s",
                            int(seqNumber), sendTimeStampString)

            # ====== Log result =============================================
            mlogger.info(
               '%s\t%d\t%d\t<d e="%d"><rtt>%.6f</rtt></d>',
               sendTimeStampString, options.instance, int(seqNumber), e, rtt
            )

         # ====== Error handling ============================================
         except socket.timeout:
            pass
         except IOError:
            logging.exception("IOError while handling a reply, restarting")
            restart = True
            break
         except:
            logging.exception("Exception while handling a reply")

         # ====== Clean-up ==================================================
         finally:
            # ====== Remove request =========================================
            with self.lock:
               if payload in self.requests: del self.requests[payload]

            # ====== Expire all timed-out requests, logging them as loss ====
            try:
               loss = [p for p in list(self.requests.keys()) if time.time() - self.requests[p] > options.timeout]
               for payload in loss:
                  [seqNumber, sendTimeStamp] = payload.decode('utf-8').strip().split(' ')
                  sendTimeStamp       = int(sendTimeStamp) / 1000000.0   # time stamp in s
                  sendTimeStampString = \
                     datetime.datetime.utcfromtimestamp(sendTimeStamp).strftime('%Y-%m-%d %H:%M:%S.%f')
                  mlogger.info(
                     '%s\t%d\t%d\t<d e="0"/>',
                     sendTimeStampString, options.instance, int(seqNumber)
                  )
                  with self.lock:
                     del self.requests[payload]
            except:
               logging.exception("Exception while writing expired packets")

      # ====== Shut down ====================================================
      logging.debug("Stopping receiver thread")



# ###### Main program #######################################################

# ====== Handle arguments ===================================================
ap = argparse.ArgumentParser(description='UDP Ping for NorNet Edge')
ap.add_argument('-i', '--instance',   help="Measurement instance ID", type=int, required=True)
ap.add_argument('-d', '--dport',      help='Destination port',        type=int, default=DEFAULT_DPORT)
ap.add_argument('-D', '--daddr',      help='Destination IP',          type=ip_address, default=DEFAULT_DADDR)
ap.add_argument('-I', '--iface',      help='Interface name',          required=True)
ap.add_argument('-S', '--psize',      help='Payload size',            type=int, default=DEFAULT_PSIZE)
ap.add_argument('-t', '--timeout',    help='Reply timeout',           type=int, default=DEFAULT_TIMEOUT)
ap.add_argument('-N', '--network_id', help='Network identifier',      type=int, default=None)
options = ap.parse_args()

if ((options.dport < 1) or (options.dport > 65535)):
   sys.stderr.write('ERROR: Invalid destination port!\n')
   sys.exit(1)
if ((options.psize < 16) or (options.psize > PAYLOAD_MAX)):
   sys.stderr.write('ERROR: Invalid payload size!\n')
   sys.exit(1)
if ((options.timeout < 1) or (options.timeout > 24*3600)):
   sys.stderr.write('ERROR: Invalid reply timeout!\n')
   sys.exit(1)
if ((options.network_id != None) and ((options.network_id < 0) or (options.network_id > 999))):
   sys.stderr.write('ERROR: Invalid network identifier!\n')
   sys.exit(1)

if options.network_id:
   # Assuming hostname is "nne<NNN>" with N of 1 to 3 digits!
   hostname = socket.gethostname()
   match    = re.search('^(nne)(\d{1,3})$', hostname)
   if match:
      nodeNumber = int(match.group(2))
      sport      = 10000 + (10 * nodeNumber) + options.network_id
   else:
      sys.stderr.write('ERROR: Hostname is not "nne<NNN>"; try without network identifier!\n')
      sys.exit(1)
else:
   sport = 0


# ====== Make sure the output directories exist =============================
for directory in [ LOG_DIRECTORY, DATA_DIRECTORY ]:
   try:
      os.makedirs(directory, 0o755, True)
   except:
      sys.stderr.write('ERROR: Unable to create directory ' + directory + '!\n')
      sys.exit(1)


# ====== Initialise logger ==================================================
MBBM_LOGGING_CONF = {
   'version': 1,
   'handlers': {
      'default': {
         'level': 'DEBUG',
         'class': 'logging.handlers.TimedRotatingFileHandler',
         'formatter': 'standard',
         'filename': (LOG_DIRECTORY + '/uping_%d.log') % (options.instance),
         'when': 'D'
      },
      'mbbm': {
         'level': 'DEBUG',
         'class': 'logging.handlers.TimedRotatingFileHandler',
         'formatter': 'mbbm',
         'filename': (DATA_DIRECTORY + '/uping_%d.dat') % (options.instance),
         'when': 'S',
         'interval': 15
      }
   },
   'formatters': {
      'standard': {
         'format': '%(asctime)s %(levelname)s [PID=%(process)d] %(message)s'
      },
      'mbbm': {
         'format': '%(message)s',
      }
   },
   'loggers': {
      'mbbm': {
         'handlers': ['mbbm'],
         'level': 'DEBUG',
         'propagate': False,
      }
   },
   'root': {
      'level': 'DEBUG',
      'handlers': ['default'],
   }
}

logging.config.dictConfig(MBBM_LOGGING_CONF)
mlogger = logging.getLogger('mbbm')


# ====== Initialise mutex and signal handlers ===============================
udpSocket = None
receiver  = None
requests  = {}
lock      = threading.Lock()

signal.signal(signal.SIGINT,  handler)
signal.signal(signal.SIGTERM, handler)


# ====== Main loop ==========================================================
seqNumber = 1
while running:
   try:
      # ====== Clean-up previous round, if necessary ========================
      if udpSocket:
         udpSocket.close()
         udpSocket = None
      if receiver:
         if receiver.isAlive():
            receiver.terminate.set()
            receiver.join()
         receiver = None
      restart = False

      # ====== Create socket ================================================
      if options.daddr.version == 4:
         family = socket.AF_INET
      else:
         family = socket.AF_INET6
      sourceIP  = netifaces.ifaddresses(options.iface)[family][0]['addr']
      udpSocket = socket.socket(family, socket.SOCK_DGRAM)
      try:
         udpSocket.bind((sourceIP, sport))
      except: # fallback to a random source port
         if sport > 0:
            udpSocket.bind((sourceIP, 0))
      udpSocket.connect((str(options.daddr), options.dport))

      # ====== Create receiver thread =======================================
      receiver = Receiver(udpSocket, lock, requests, timeout=options.timeout)
      receiver.start()

      # ====== Send loop ====================================================
      logging.debug("Starting")
      while running and not restart:
         # ====== Send UDP Ping =============================================
         sendTimeStamp = time.time()
         payloadString = \
            '%d %d' % (seqNumber, int(sendTimeStamp * 1000000))
         if len(payloadString) < options.psize:
            payloadString = (options.psize - len(payloadString)) * ' ' + payloadString

         payload = payloadString.encode('utf-8')
         with lock:
            requests[payload] = sendTimeStamp
         udpSocket.send(payload)

         # ====== Increment sequence number =================================
         if seqNumber >= sys.maxsize:
            seqNumber = 1   # roll over
         else:
            seqNumber = seqNumber + 1

         # ====== Wait ======================================================
         time.sleep(1 - (time.time() - sendTimeStamp))

   # ====== Handle error ====================================================
   except:
      logging.exception("Error")
      time.sleep(SLEEP_ON_ERROR)


# ====== Shut down ==========================================================
if receiver:
   try:
      receiver.join(5000)
   except:
      pass
logging.debug("Exiting")
