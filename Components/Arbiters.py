from Components.BasicComponent import Component
from simpyExtensions.util import CrossbarGet, NewEvent
import random
from SimSettings import simTicksPerCycle
from statistics import mean

class Crossbar(Component):

    def __init__(self, env, name="", parent=None, inPorts=2,outPorts=1,pushMode=False,monitorBW=False,monitorInterval=500):

        Component.__init__(self,env, name, parent)

        self.fromDn={i:self for i in range(outPorts)} if outPorts>1 else self
        self.fromUp={i:self for i in range(inPorts)} if inPorts>1 else self
        self.decisionTimeStamps={}
        self.inPorts=inPorts
        self.outPorts=outPorts
        self.pushMode=pushMode
        self.peekEvents=[None]*self.inPorts
        self.unMaskEvents=[None]*self.inPorts

        self.routes=[None]*self.inPorts #stores the destination outPort of packets on inPorts (None is no packets)
        self.routedPktList=[None]*self.inPorts #stores the modified packet due to routing on each inPort, or simply the original packet
        self.lastport=[-1]*self.outPorts

        self.get_queues=[]
        for i in range(self.outPorts):
            self.get_queues.append([])

        self.arbEvents=[None]*self.outPorts
        self.monitorBW=monitorBW
        self.monitorInterval=monitorInterval*simTicksPerCycle
        self.timeSamples=[]
        self.totalBitsSent=[]
        self.lastActivity=[]
        self.firstActivity=[]
        self.bw=[]

        for inPort in  range(self.inPorts):
            self.lastActivity.append([])
            self.firstActivity.append([])
            self.totalBitsSent.append([])
            self.bw.append([])

            for outPort in range(self.outPorts):
                self.lastActivity[inPort].append(None)
                self.firstActivity[inPort].append(None)
                self.totalBitsSent[inPort].append(0)
                self.bw[inPort].append([])

    def route(self, peekEvent):

        inPort=self.peekEvents.index(peekEvent) #the inPort at which the packet was detected
        pkt=peekEvent.value  # the original packet before 

        #------Customizable Routing Routine ----–--#
        """This code block should assign an outPort for
            the packet to be directed to. it can also
             manipulate the pkt"""

        outPort=0
        #--------------END-----------------------#


        #-----maintaining list of routed packets and their destinations---#
        self.routes[inPort]=outPort
        self.routedPktList[inPort]=pkt
        inPortName=self.toUp[inPort].name if self.inPorts>1 else self.toUp.name
        outPortName=self.toDn[outPort].name if self.outPorts>1 else self.toDn.name
        self.Log('DEBUG','Packet {} from {} was routed to {}'.format(pkt.uid, inPortName, outPortName))

    def unMask(self,pkt,outport):

        """ function to unmask a request to send from an upstream port to participate in the arbitration round.
            In the backend, the arbiter will peek into all its upstream ports to identify ports with packets to send.
            Each such packet is passed to this function which returns an event that may or may not readily successful.
            In the backend, the arbiter waits until at least one packet is unmasked and if multiple packets are unmasked,
            if performs an arbitration between them.

            The default of this function returns a successful event, indicating that the packet is readily unmasked.
            But this can be customized to return a not-yet-successful event.

        """
        return NewEvent(self.env).succeed()

    def arbitratePkts(self,pktList, outPort=0):
        """ a customizable function that performs the arbitration between unmasked packets.
            the default is to choose a random input port to proceed to the outPort passed as
            argument"""

        activeports=[i for i, pkt in enumerate(pktList) if pkt != None]

        if activeports:
            candidate=random.choice(activeports)
            self.lastport[outPort]=candidate   
        else:
            candidate=None
        return candidate

    def postDecisionMsg(self,candidate):

        inPortName=self.toUp[candidate].name if self.inPorts>1 else self.toUp.name
        outPortName=self.toDn[self.routes[candidate]].name if self.outPorts>1 else self.toDn.name                
        self.Log("INFO", "Random Arbitration elected packet {} from {} to proceed towards {}".format(self.routedPktList[candidate].uid, inPortName, outPortName))

    def run(self):
        
        if self.monitorBW:
            self.env.process(self.bwMonitor())

        self.run_init()

        if self.pushMode:
            for outPort in range(self.outPorts-1):
                self.env.process(self.runOutPort(outPort))

            yield self.env.process(self.runOutPort(self.outPorts-1))
        else:
            yield self.env.timeout(1)

    def run_init(self):
        
        if self.inPorts==1:

            self.peekEvents=[self.toUp.peek(0,caller=self)]

        else:
            self.peekEvents=[self.toUp[inPort].peek(inPort,caller=self) for inPort in range(self.inPorts)]

        for inPort in range(self.inPorts):

            if self.peekEvents[inPort].triggered:
                self.route(self.peekEvents[inPort])
                self._postPeekProcessing(self.peekEvents[inPort])

            else:
                self.peekEvents[inPort].callbacks.append(self._postPeekProcessing)

    def runOutPort(self,outPort):

        while True:
            
            pkt= yield self.get(outPort)
            inPort=self.lastport[outPort]
            
            if self.firstActivity[inPort][outPort]==None:
                self.firstActivity[inPort][outPort]=self.env.now

            caller=self.toUp[inPort] if self.inPorts>1 else self.toUp
            if self.outPorts>1:
                yield self.toDn[outPort].put(pkt,caller=caller)

            else:

                yield self.toDn.put(pkt,caller=caller)

            self.totalBitsSent[inPort][outPort]+=8*pkt.getBytes()
            self.lastActivity[inPort][outPort]=self.env.now

    def get(self, outPort=0):

        return CrossbarGet(self, outPort)

    def _postPeekProcessing(self,peekEvent):

        inPort=self.peekEvents.index(peekEvent)

        if self.routes[inPort]==None:

            self.route(peekEvent)

        outPort=self.routes[inPort]
        pkt=self.routedPktList[inPort]

        #create unmask event
        self.unMaskEvents[inPort]=self.unMask(pkt,outPort)

        outPortName=self.toDn[outPort].name if self.outPorts>1 else self.toDn.name
        inPortName=self.toUp[inPort].name if self.inPorts>1 else self.toUp.name

        self.Log('DEBUG','Creating unMask event ({}) for packet {} to proceed from {} to {}.'\
            .format(type(self.unMaskEvents[inPort]).__name__, pkt.uid, inPortName, outPortName )) 

        activeInPorts=[inPort for inPort in range(self.inPorts) if (self.routes[inPort]==outPort)]

        arbScheduled=False

        for inPort in activeInPorts:

            if self.unMaskEvents[inPort].triggered:
                arbScheduled=True

                if not self.arbEvents[outPort]:
                    self._schedule_arbitration(self.unMaskEvents[inPort])

                    self.Log('DEBUG','One or more Packets for outPort {} are unMasked. Arbitration will now proceed'\
                        .format(outPortName)) 
                break

            else:
                self.unMaskEvents[inPort].callbacks.append(self._schedule_arbitration) 


        if not arbScheduled:

            self.Log('DEBUG','No unMasked Packets for outPort {}. Adding callbacks to schedule an arbitration Once any packet is unMasked.'\
                .format(outPortName)) 

    def _schedule_arbitration(self, unMaskEvent):

        if unMaskEvent not in self.unMaskEvents:
            return

        unMaskedPort=self.unMaskEvents.index(unMaskEvent)
        outPort=self.routes[unMaskedPort]

        if not self.arbEvents[outPort] and self.get_queues[outPort]:
            self.arbEvents[outPort]=NewEvent(self.env,outPort)
            self.arbEvents[outPort].callbacks.append(self._do_get)
            self.arbEvents[outPort].succeed()
            outPortName=self.toDn[outPort].name if self.outPorts>1 else self.toDn.name
            # self.Log('DEBUG','unMasked Packets for outPort {} Readily Available. Arbitration will proceed.'\
            #     .format(outPortName)) 

    def _do_get(self, arbitrateEvent):


        # unMaskedPort=self.unMaskEvents.index(unMaskEvent)
        outPort=arbitrateEvent.item
        if not self.get_queues[outPort]:
            return
        
        unMaskedInPorts=[inPort for inPort in range(self.inPorts) if (self.routes[inPort]==outPort and self.unMaskEvents[inPort].triggered)]
        pktList=[(self.routedPktList[inPort] if inPort in unMaskedInPorts else None) for inPort in range(self.inPorts)]
        
        if any(pktList):
            previous=self.lastport[outPort]
            chosenPort=self.arbitratePkts(pktList,outPort)
            self.postDecisionMsg(chosenPort)
            pkt=pktList[chosenPort]

        else:
            self.Log('FATAL_ERROR','Unexpected empty list of unmasked Packets to proceed to outPort {}'\
                .format(outPort))

        upstream=self.toUp[chosenPort] if self.inPorts>1 else self.toUp

        upGet=upstream.get(chosenPort,caller=self)

        if upGet:
            preGetDelay=upstream.addPreGetDelay(pkt)
            postGetDelay=upstream.addPostGetDelay(pkt)
            upstream.Log("DEBUG","PreGetDelay is {} ticks. PostGetDelay is {} ticks".format(preGetDelay,postGetDelay))
            self.get_queues[outPort][0].succeed(pkt, delay=preGetDelay)
            self.get_queues[outPort].pop(0)

            cleanupEvent=NewEvent(self.env,outPort)
            cleanupEvent.callbacks.append(self._cleanup)
            cleanupEvent.succeed(chosenPort,delay=preGetDelay+postGetDelay)
        else:
            self.lastport[outPort]=previous
            cleanupEvent=NewEvent(self.env,outPort)
            cleanupEvent.callbacks.append(self._cleanup)
            cleanupEvent.succeed(chosenPort,delay=simTicksPerCycle)
            self.Log('DEBUG','Arbitration is re-scheduled for the next cycle')

    def _cleanup(self, cleanupEvent):


        outPort=cleanupEvent.item
        activatedInPort=cleanupEvent.value
        pkt=self.routedPktList[activatedInPort]

        if activatedInPort==self.lastport[outPort]:
            self.Log('DEBUG','Finished Sending Packet {} sent from inPort {} towards outPort {}. Cleaning up and refreshing Peek and UnMask Events'\
                .format(pkt.uid, activatedInPort, outPort))


        self.routes[activatedInPort]=None
        self.routedPktList[activatedInPort]=None
        self.unMaskEvents[activatedInPort]=None
        self.arbEvents[outPort]=None

        upstream=self.toUp[activatedInPort] if self.inPorts>1 else self.toUp
        
        self.Log('DEBUG','Refreshing Peek onto inPort {}.'.format(activatedInPort))
        self.peekEvents[activatedInPort]=upstream.peek(activatedInPort,caller=self)


        if self.peekEvents[activatedInPort].triggered:
            self._postPeekProcessing(self.peekEvents[activatedInPort])
        
        else:
            self.peekEvents[activatedInPort].callbacks.append(self._postPeekProcessing)

        for inPort in range(self.inPorts):
            if self.routes[inPort]==outPort and inPort!=activatedInPort:
                self._postPeekProcessing(self.peekEvents[inPort])

    def bwMonitor(self):

        lastTotalBitsSent=[]
        for ip in  range(len(self.totalBitsSent)):
            lastTotalBitsSent.append([])
            for op in range(len(self.totalBitsSent[ip])):
                lastTotalBitsSent[ip].append(0)
               
        bw_interval=0

        while True:

            yield self.env.timeout(self.monitorInterval)

            for ip in  range(len(self.totalBitsSent)):
                for op in range(len(self.totalBitsSent[ip])):

                    bw_interval = (self.totalBitsSent[ip][op] - lastTotalBitsSent[ip][op]) / (self.monitorInterval)
                    self.bw[ip][op].append(bw_interval)
                    lastTotalBitsSent[ip][op]=self.totalBitsSent[ip][op]

            self.timeSamples.append(self.env.now)

    def dumpBwVsTime(self):

        #returns two lists: one for the time stamps indicating the closure of monitoring interval
        # (in cycles) and another for the recorded bw during that interval
        name=''
        time= [name]+[t/simTicksPerCycle for t in self.timeSamples]
        data=[]

        for ip in range(len(self.totalBitsSent)):
            for op in range(len(self.totalBitsSent[ip])):
                adjustedBw=[simTicksPerCycle*b for b in self.bw[ip][op]]
                if any(adjustedBw):
                    data.append(['{}/{}'.format(ip,op)]+adjustedBw)

        return time, data

    def dumpStats(self):
        
        """returns a list of statistics on the operation: 
                1- """

        avData=[]
        for ip in range(len(self.totalBitsSent)):
            for op in range(len(self.totalBitsSent[ip])):

                maxbw=simTicksPerCycle*max(self.bw[ip][op]) if self.bw[ip][op]!=[] else 0
                firstActivity=self.firstActivity[ip][op] if self.firstActivity[ip][op] else 0
                lastActivity=self.lastActivity[ip][op] if self.lastActivity[ip][op] else 0
                totalBitsSent=self.totalBitsSent[ip][op]

                activeDuration=(lastActivity-firstActivity) if firstActivity!=None else 0
                
                averagebw0=simTicksPerCycle*(totalBitsSent/activeDuration) if activeDuration else 0
                averagebw1=simTicksPerCycle*(totalBitsSent/self.env.now)
                averagebw2=simTicksPerCycle*mean(self.bw[ip][op]) if self.bw[ip][op] else 0
                averagebw3=(simTicksPerCycle)*(self.monitorInterval*sum([b**2 for b in self.bw[ip][op]]))/totalBitsSent if totalBitsSent else 0

                avData.append(['{}/{}'.format(ip,op)]+[round(maxbw,2),round(averagebw0,2),round(averagebw1,2),round(averagebw2,2),round(averagebw3,2),totalBitsSent,int(firstActivity/simTicksPerCycle),int(lastActivity/simTicksPerCycle),int(self.env.now/simTicksPerCycle)])

        return avData

class RoundRobinCrossbar(Crossbar):
    
    def postDecisionMsg(self,candidate):

        inPortName=self.toUp[candidate].name if self.inPorts>1 else self.toUp.name
        outPortName=self.toDn[self.routes[candidate]].name if self.outPorts>1 else self.toDn.name                
        self.Log("INFO", "RoundRobin Arbitration elected packet {} from {} to proceed towards {}".format(self.routedPktList[candidate].uid, inPortName, outPortName))

    def arbitratePkts(self,pktList,outPort=0):


        activeports=[i for i, pkt in enumerate(pktList) if pkt != None]
        # self.Log("DEBUG", "Ports {} are unmasked for outPort {}".format(activeports,outPort))

        count=0
        candidate=(self.lastport[outPort]+1)%self.inPorts

        while count<self.inPorts:

            if pktList[candidate]:
                self.lastport[outPort]=candidate   
                inPortName=self.toUp[candidate].name if self.inPorts>1 else self.toUp.name
                outPortName=self.toDn[outPort].name if self.outPorts>1 else self.toDn.name

                unMaskedPorts=[self.toUp[port].name for port in activeports] if self.inPorts>1 else [self.toUp.name]
                self.Log("INFO", "RoundRobin arbitration between unmasked ports {} elected packet {} from {} to proceed towards {}".format(unMaskedPorts,pktList[candidate].uid, inPortName, outPortName))
                return candidate

            else:
                count+=1
                candidate=(candidate+1)%self.inPorts

        return None

class WeightedRoundRobinCrossbar(Crossbar):

    def __init__(self, env, name="", parent=None, inPorts=2,outPorts=1,pushMode=False,monitorBW=False,monitorInterval=500,weights=None):

        Crossbar.__init__(self,env,name,parent,inPorts,outPorts,pushMode,monitorBW,monitorInterval)
        if len(weights)==self.inPorts:
            self.weights=weights
        else:
            self.Log('FATAL_ERROR',"provide a list of integer weights of size {} as an argument (weights=[])".format(self.inPorts))
        
        self.grants=[0]*self.inPorts

    def arbitratePkts(self,pktList,outPort=0):

        activeports=[i for i, pkt in enumerate(pktList) if pkt != None]

        count=0

        candidate=self.lastport[outPort]
        decisionMade=False
        selectedCandidate=None

        while count<self.inPorts and not decisionMade:

            if pktList[candidate]:

                if self.weights[candidate]>self.grants[candidate]:

                    selectedCandidate=candidate
                    decisionMade=True

                elif selectedCandidate==None:
                    selectedCandidate=candidate

                if self.grants[candidate]==self.weights[candidate]:
                    self.grants[candidate]=0

            count=(count+1)
            candidate=(candidate+1)%self.inPorts

        if selectedCandidate!=None:

            self.lastport[outPort]=selectedCandidate
            self.grants[selectedCandidate]+=1
            inPortName=str((self.toUp[selectedCandidate].name if self.inPorts>1 else self.toUp.name))
            outPortName=str((self.toDn[outPort].name if self.outPorts>1 else self.toDn.name))
            unMaskedPorts=[self.toUp[port].name for port in activeports] if self.inPorts>1 else [self.toUp.name]
            self.Log("INFO", "Weighted RoundRobin arbitration elected packet {} from {} to proceed towards {}".format(pktList[selectedCandidate].uid, inPortName, outPortName))

            return selectedCandidate

        return None

class FixedPriorityCrossbar(Crossbar):
    
    def __init__(self, env, name="", parent=None, inPorts=2,outPorts=1,priorities=None,pushMode=False,monitorBW=False, monitorInterval=500):
        Crossbar.__init__(self,env, name, parent, inPorts,outPorts,pushMode,monitorBW, monitorInterval)

        if not priorities:
            self.priorities=[0]*self.inPorts
            self.priorityClasses=1

        elif len(priorities)==self.inPorts:
            if all([isinstance(p,int) for p in priorities]):
                self.priorities=priorities
                self.priorityClasses=max(self.priorities)+1

            else:
                self.Log("FATAL_ERROR","All priorities must be integers")
        else:
            self.Log("FATAL_ERROR","the number of priorities provided must be equal to the number of inPorts")
        
        self.lastportPerClass=[]

        for priorityClass in range(self.priorityClasses):
            self.lastportPerClass.append([-1]*self.outPorts)
    
    def postDecisionMsg(self,candidate):

        inPortName=self.toUp[selectedCandidatedate].name if self.inPorts>1 else self.toUp.name
        outPortName=self.toDn[self.routes[candidate]].name if self.outPorts>1 else self.toDn.name                
        self.Log("INFO", "FixedPriority Arbitration elected packet {} from {} to proceed towards {}".format(self.routedPktList[candidate].uid, inPortName, outPortName))

    def arbitratePkts(self,pktList,outPort=0):

        activeports=[i for i, pkt in enumerate(pktList) if pkt != None]

        self.Log("DEBUG", "Ports {} are unmasked for outPort {}".format(activeports,outPort))
        maxpriority=max([self.priorities[port] for port in activeports])

        for port in activeports:
            if self.priorities[port]<maxpriority:
                pktList[port]=None

        count=0
        candidate=(self.lastportPerClass[maxpriority][outPort]+1)%self.inPorts

        while count<self.inPorts:

            if pktList[candidate]:
                self.lastportPerClass[maxpriority][outPort]=candidate   
                self.lastport[outPort]=candidate 
                inPortName=self.toUp[candidate].name if self.inPorts>1 else self.toUp.name
                outPortName=self.toDn[outPort].name if self.outPorts>1 else self.toDn.name
                unMaskedPorts=[self.toUp[port].name for port in activeports] if self.inPorts>1 else [self.toUp.name]

                self.Log("INFO", "Fixed Priority arbitration between unmasked ports {} elected packet {} from {} to proceed towards {}".format(unMaskedPorts,pktList[candidate].uid, inPortName, outPortName))
                return candidate

            else:
                count+=1
                candidate=(candidate+1)%self.inPorts

        return None

