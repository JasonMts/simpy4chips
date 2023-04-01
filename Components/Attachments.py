import random
from Components.BasicComponent import Unit
from Components.Packets import BasePacket
from SimSettings import simTicksPerCycle
import simpy
#---------------------------------------------------------------------------------
# Attachements: Trafficator and Traffic Sink
#---------------------------------------------------------------------------------
class Trafficator(Unit):

    def __init__(self,env,name,parent=None):
        Unit.__init__(self,env,name,parent)
        self.fromDn=self
        self.pktList=[]
        self.sendDone=Event(self.env)

    def run(self):

        if not self.toDn:
            self.Log("FATAL_ERROR","Trafficator Not Connected to Downstream")

        yield self.env.process(self.runScenario())


    def runScenario(self):

        while self.pktList:

            yield self.toDn.put(self.pktList.pop(0))

        self.sendDone.succeed()

    def addPacket(self,pkt):

        self.pktList.append(pkt)

class TrafficSink(Unit):

    def __init__(self, env, name, parent=None,bytesPerTick=16,monitorBW=True,monitorInterval=250):
        Unit.__init__(self,env,name,parent)
        self.fromUp = self
        self.expectedBytes=0
        self.receivedBytes=0
        self.bytesPerTick=bytesPerTick
        self.timeSamples=[]
        self.bw=[]
        self.monitorBW=monitorBW
        self.monitorInterval = monitorInterval* simTicksPerCycle
        self.receiveDone=Event(self.env)
        self.totalBitsSent = 0
        self.receivedPkts=0
        self.expectedPkts=0

    def run(self):
        if self.monitorBW:
            self.env.process(self.bwMonitor())

        self.Log("DEBUG","Expecting {} bytes".format(self.expectedBytes))

        while self.receivedBytes!=self.expectedBytes:
            pkt= yield self.toUp.get()
            self.Log("DEBUG","Extracted packet {} from {}".format(pkt.uid,self.toUp.name))
            self.updateReceivedBytes(pkt)
            self.totalBitsSent+=pkt.getBytes()*8
            yield self.env.timeout(pkt.getTicks(self.bytesPerTick)*simTicksPerCycle)
            self.Log("DEBUG","Received {} out of {} expected bytes".format(self.receivedBytes,self.expectedBytes))

        self.receiveDone.succeed()

        self.Log('INFO',"Completed Receiving {} bytes out of expected {} bytes ({} out of {} pkts)".format(self.receivedBytes,self.expectedBytes,self.receivedPkts,self.expectedPkts))
        while True:
            pkt=yield self.toUp.get()
            self.Log('FATAL_ERROR',"Received unexpected packet {} after being done.".format(pkt.uid))

    def updateReceivedBytes(self,pkt):
        self.receivedPkts+=1
        self.receivedBytes+=pkt._payloadbytes

    def updateExpectedBytes(self,pkt):

        self.expectedPkts+=1
        self.expectedBytes+=pkt._payloadbytes

    def bwMonitor(self):
        lastTotalBitsSent = 0
        bw_interval = 0
        while True:
            yield self.env.timeout(self.monitorInterval)
            bw_interval = (self.totalBitsSent - lastTotalBitsSent) / self.monitorInterval
            self.bw.append(bw_interval)
            self.timeSamples.append(self.env.now)
            lastTotalBitsSent = self.totalBitsSent



