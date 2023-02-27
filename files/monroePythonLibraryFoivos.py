#!/usr/bin/python3
# -*- coding: utf-8 -*-

import json
import logging
import logging.config
import os
import sys
import subprocess
import zmq
import netifaces
import time

def listenToMetadataBroadcasts(topic = 'MONROE.META.DEVICE.MODEM', timeout = 3600):
    """
    This function just prints on the screen the metadata broadcasts of the specified topic.
    It is useful during live development at a node or debugging.
    """
    startFunctionTime = int(time.time())
    # ====== Initialise ZeroMQ metadata stream ==================================
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect('tcp://172.17.0.1:5556')
    socket.setsockopt_string(zmq.SUBSCRIBE, topic)
    # The descriptions of the fields for each metadata message are at the 
    # appendix B of the MONROE manual.
    while True:
        # ------ Read metadata ---------------------------------------------------
        data = socket.recv().decode('utf-8').split(' ', 1)
        print(data)
        if ((int(time.time()) - startFunctionTime) > timeout):
            return

def getWiredInterfaceSourceIP(interfaceName="eth0"):
    wiredDict = {"Wired": {"interface": "Wired", "sourceIPv4": None, "sourceIPv6": None}}
    # get the IPv4 and IPv6 of the interface
    addrs = netifaces.ifaddresses(interfaceName)
    ipv4 = addrs.get(netifaces.AF_INET, [])
    if ipv4 != []:
        wiredDict["Wired"]["sourceIPv4"] = ipv4[0]["addr"]
    ipv6 = addrs.get(netifaces.AF_INET6, [])
    if ipv6 != []:
        wiredDict["Wired"]["sourceIPv6"] = ipv6[0]["addr"]
    return wiredDict

def mapMobileOperatorsToInterfacesAndSourceIPs(targetOperatorList, timeout = 10):
    operatorDict = {key: {"interface": None, "sourceIPv4": None, "sourceIPv6": None} for key in  targetOperatorList}
    startFunctionTime = int(time.time())
    # ====== Initialise ZeroMQ metadata stream ==================================
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect('tcp://172.17.0.1:5556')
    socket.setsockopt_string(zmq.SUBSCRIBE, 'MONROE.META.DEVICE.MODEM')
    # The descriptions of the fields for each metadata message are at the 
    # appendix B of the MONROE manual.
    while True:
        # ------ Read metadata ---------------------------------------------------
        data = socket.recv().decode('utf-8').split(' ', 1)
        try:
            topic    = data[0]
            metadata = json.loads(data[1])
        except Exception as e:
            print('WARNING: Cannot read metadata: ' + str(e) + '\n')
        # ------ Extract relevant meatadata ---------------------------------
        if ((topic != None) and (metadata != None)):
            if (topic.startswith('MONROE.META.DEVICE.MODEM')):
                try:
                    # needed to choose the interface to send the traffic
                    InternalInterface     = metadata.get("InternalInterface") # e.g. "op2"
                    Operator     = metadata.get("Operator") # e.g. "Telenor"
                    # InterfaceName     = metadata.get("InterfaceName") # e.g. "nlw_1-1"
                    # nice to have
                    metadataMCCMNC = str(metadata.get("IMSIMCCMNC"))
                    if metadataMCCMNC != None:
                        metadataMCC    = metadataMCCMNC[0:3]
                        metadataMNC    = metadataMCCMNC[3:]
                    metadataICCID  = str(metadata.get("ICCID"))
                except Exception as e:
                    print('WARNING: Cannot read MONROE.META.DEVICE.MODEM: ' + str(e) + '\n')
            # ------ assign the relevant values to the dict if they are not present ---------------------------------
            if Operator in targetOperatorList:
                if operatorDict[Operator]["interface"] == None:
                    operatorDict[Operator]["interface"] = InternalInterface
                    operatorDict[Operator]["IMSIMCCMNC"] = metadataMCCMNC
                    operatorDict[Operator]["metadataMCC"] = metadataMCC
                    operatorDict[Operator]["metadataMNC"] = metadataMNC
                    operatorDict[Operator]["metadataICCID"] = metadataICCID
                    # get the IPv4 and IPv6 of the interface
                    addrs = netifaces.ifaddresses(InternalInterface)
                    ipv4 = addrs.get(netifaces.AF_INET, [])
                    if ipv4 != []:
                        operatorDict[Operator]["sourceIPv4"] = ipv4[0]["addr"]
                    ipv6 = addrs.get(netifaces.AF_INET6, [])
                    if ipv6 != []:
                        operatorDict[Operator]["sourceIPv6"] = ipv6[0]["addr"]
        # ------ check if we have reached the timeout or have already gathered info for all the interfaces ---------
        if ((int(time.time()) - startFunctionTime) > timeout) or (None not in [operatorDict[key]["interface"] for key in operatorDict.keys()]):
            return operatorDict

