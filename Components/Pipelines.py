from Components.BasicComponent import Component
from simpyExtensions.util import NewEvent, PipelinePut
from Components.Buffers import CreditBuffer
from SimSettings import simTicksPerCycle
#-----------------------------------------------------------------
#Generic Pipeline, Flow Controlled Pipeline
#-----------------------------------------------------------------

class Pipeline(Component):
    """Abstract base class for a basic pipeline.

    You can :meth:`put()` something into the pipeline. If a :meth:`put()` request cannot complete
    immediately (for example if the resource has reached a capacity limit) it
    is enqueued in the :attr:`put_queue` for later processing.

    usage: yield pipeline.put(item)
    behaviour: it will block until the item is completely passed through the pipeline.
    This requires the item to have a getTicks() method returning the number of ticks that
    the item will hog the pipeline for. THIS IS DIFFERENT THAN THE TIME TAKEN TO REACH THE
    END OF THE PIPELINE (that is given by the depth parameter)

    """

    def __init__(self, env, name, parent=None, depth=1, putBytesPerCycle=16,monitorBW=False,monitorInterval=250):

        Component.__init__(self,env, name, parent)
        self.fromDn=self
        self.fromUp=self
        self.putBusy=False
        self.putBytesPerCycle=putBytesPerCycle
        self.depth = depth
        """Queue of pending *put* requests."""
        self.put_queue = []
        self.putDebt=0
        self.monitorBW=monitorBW
        self.monitorInterval=monitorInterval*simTicksPerCycle
        self.timeSamples=[]
        self.totalBitsSent=0
        self.lastActivity=None
        self.firstActivity=None
        self.bw=[]

    def run(self):
        if self.monitorBW:
            yield self.env.process(self.bwMonitor())
        else:
            yield self.env.timeout(1)

    def put(self, item,caller=None) :
        """Request to put something into the resource and return a
        :class:`Put` event, which gets triggered once the request
        succeeds."""
        return PipelinePut(self, item, caller=caller)

    def addPostPutDelay(self,item):

        ticks,debt=item.getTicks(self.putBytesPerCycle)
        extra=int(self.putDebt+debt)
        ticks+=extra
        return ticks*simTicksPerCycle

    def prePutMsg(self, event):

        """ This function adds a put delay after an item has been inserted out
        into the store. When yield store.put(item) is called, it will only 
        unblock only after:
             1- the item has been actually inserted into the store, ie, store.items.append(item)
            THEN;
             2- the number of ticks returned by this function has passed"""

        self.Log( 'INFO', "Started sending packet {} down the pipeline. This will take {} simTicks".format(event.item.uid,self.addPostPutDelay(event.item)))

    def postPutMsg(self, event):

        """ This function adds a put delay after an item has been inserted out
        into the store. When yield store.put(item) is called, it will only 
        unblock only after:
             1- the item has been actually inserted into the store, ie, store.items.append(item)
            THEN;
             2- the number of ticks returned by this function has passed"""

        self.Log( 'INFO', "Finished sending Packet {} down the pipeline".format(event.item.uid))


    def _putBusy(self,*args):

        if self.putBusy:
            self.Log( 'FATAL_ERROR', "Trying to put() through the pipeline while busy")
        else:    
            self.putBusy=True

    def _putReady(self,*args):

        self.putBusy=False

    def _putdelay(self,item):

        if not hasattr(self.toDn,'put'):
            self.Log("FATAL_ERROR","{} has no put method")
        yield self.env.timeout(self.depth*simTicksPerCycle) #time for first flit to be received
        yield self.toDn.put(item) # writing the packet into downstream

    def _updatePutDebt(self,item):
        ticks,debt=item.getTicks(self.putBytesPerCycle)
        self.putDebt=(self.putDebt+debt)-int(self.putDebt+debt)

    def _updateTotalBitsSent(self,event):
        
        self.totalBitsSent += event.item.getBytes()*8
        self.lastActivity=self.env.now

    def _do_put(self, event):
        """Perform the *put* operation.

        This method needs to be implemented by subclasses. If the conditions
        for the put *event* are met, the method must trigger the event (e.g.
        call :meth:`Event.succeed()` with an apropriate value).

        This method is called by :meth:`_trigger_put` for every event in the
        :attr:`put_queue`, as long as the return value does not evaluate
        ``False``.
        """
        pkt=event.item
        ticks=self.addPostPutDelay(pkt)
        event.callbacks.append(self.postPutMsg)
        event.callbacks.append(self._updateTotalBitsSent)
        self.prePutMsg(event)
        event.succeed(delay=ticks)
        self.env.process(self._putdelay(pkt))

        if self.firstActivity==None:
            self.firstActivity=self.env.now
        
        self._updatePutDebt(pkt)

    def _trigger_put(self,put_event=None):
        """This method is called once a new put event has been created or a get
        event has been processed.

        The method iterates over all put events in the :attr:`put_queue` and
        calls :meth:`_do_put` to check if the conditions for the event are met.
        If :meth:`_do_put` returns ``False``, the iteration is stopped early.
        """

        # Maintain queue invariant: All put requests must be untriggered.
        # This code is not very pythonic because the queue interface should be
        # simple (only append(), pop(), __getitem__() and __len__() are
        # required).
        idx = 0
        while idx < len(self.put_queue):
            put_event = self.put_queue[idx]
            proceed = self._do_put(put_event)
            if not put_event.triggered:
                idx += 1
            elif self.put_queue.pop(idx) != put_event:
                raise RuntimeError('Put queue invariant violated')

            if not proceed:
                break


    def bwMonitor(self):

        lastTotalBitsSent=0
               
        bw_interval=0

        while True:

            yield self.env.timeout(self.monitorInterval)
            bw_interval = (self.totalBitsSent - lastTotalBitsSent) / (self.monitorInterval)
            self.bw.append(bw_interval)
            lastTotalBitsSent=self.totalBitsSent
            self.timeSamples.append(self.env.now)

    def dumpBwVsTime(self):

        """this function returns a list of useful statistics about the write side of the buffer throughout the simulation:
            - maximum bandwidth (across monitoring intervals)
            - average bandwidth (averaged over all monitoring intervals)*
            - Total number of bits written into the buffer over the simulation 
            - firstActivity: first time writing the buffer was recorded
            - lastActivity: last time writing the buffer was recorded
            - simulation time: the total time simulation took (in cycles)

            *4 different methods for calculating the averages are provided.

            Note that the first element of each of the lists is a string prefix(empty by default) providing information for further   a tuple where data format is a list  of which the first element is a string giving 
            processing the actual data starts with index 1 of these lists instead of 0.

            The values are adjusted for the simTicksPerCycle so the time is in hardware cycles and the bandwidth is in Gbps"""


        name=''
        time= [name]+[t/simTicksPerCycle for t in self.timeSamples]
        sendBw= [name]+[bw*simTicksPerCycle for bw in self.bw]

        return time, sendBw

    def dumpStats(self):
        
        """returns a list of statistics on the operation: 
                1- """
        name=''
        maxbw=simTicksPerCycle*max(self.bw) if self.bw!=[] else 0
        firstActivity=self.firstActivity if self.firstActivity else 0
        lastActivity=self.lastActivity if self.lastActivity else 0
        totalBitsSent=self.totalBitsSent
        activeDuration=(self.lastActivity-self.firstActivity) if self.firstActivity!=None else 0

        averagebw0=simTicksPerCycle*(totalBitsSent/activeDuration) if activeDuration  else 0
        averagebw1=simTicksPerCycle*(totalBitsSent/self.env.now)
        averagebw2=simTicksPerCycle*mean(self.bw) if self.bw else 0
        averagebw3=(simTicksPerCycle)*(self.monitorInterval*sum([b**2 for b in self.bw]))/totalBitsSent if totalBitsSent  else 0

        stats=[name,round(maxbw,2),round(averagebw0,2),round(averagebw1,2),round(averagebw2,2),round(averagebw3,2),totalBitsSent,int(firstActivity/simTicksPerCycle),int(lastActivity/simTicksPerCycle),int(self.env.now/simTicksPerCycle)]
        
        return stats

class FlowControlledPipeline(Pipeline):
    """Abstract base class for a basic pipeline.

    You can :meth:`put()` something into the pipeline.If a :meth:`put()` request cannot complete
    immediately (for example if the resource has reached a capacity limit) it
    is enqueued in the :attr:`put_queue` for later processing.

    usage: yield pipeline.put(item)
    behaviour: it will block until the item is completely passed through the pipeline.
    This requires the item to have a getTicks() method returning the number of ticks that
    the item will hog the pipeline for. THIS IS DIFFERENT THAN THE TIME TAKEN TO REACH THE
    END OF THE PIPELINE (that is given by the depth parameter)

    """

    def __init__(self, env, name, parent=None, depth=1,putBytesPerCycle=16,initCredits=4,monitorBW=False,monitorInterval=250):

        Pipeline.__init__(self,env, name, parent,depth,putBytesPerCycle,monitorBW,monitorInterval)
        self.CreditBuffer=CreditBuffer(self.env,'creditbuffer',parent=self, initCredits=initCredits)
        self.initCredits=initCredits

    def waitForCredit(self,*args,**kwargs):

        return self.CreditBuffer.peek()

    def _increment_credit(self,*args):

        if len(self.CreditBuffer.items)==self.initCredits:

            self.Log( 'FATAL_ERROR', "received credit while credit counter is saturated")

        self.CreditBuffer.put(1)
        self.Log('INFO', "credit received from downstream")

    def putCredit(self,*args):

        putCreditEvent=NewEvent(self.env)
        putCreditEvent.callbacks+=[self._increment_credit,self._trigger_put]
        self.toDn.Log('INFO', "credit dispatched")
        putCreditEvent.succeed(delay=self.depth*simTicksPerCycle)

    def _do_put(self, event):
        """Perform the *put* operation.

        This method needs to be implemented by subclasses. If the conditions
        for the put *event* are met, the method must trigger the event (e.g.
        call :meth:`Event.succeed()` with an apropriate value).

        This method is called by :meth:`_trigger_put` for every event in the
        :attr:`put_queue`, as long as the return value does not evaluate
        ``False``.
        """
        if self.CreditBuffer.items:

            self.CreditBuffer.get()
            self.Log( 'DEBUG', "credit consumed. {} remaining credits".format(len(self.CreditBuffer.items)))
            
            pkt=event.item
            ticks=self.addPostPutDelay(pkt)
            event.callbacks.append(self.postPutMsg)
            event.callbacks.append(self._updateTotalBitsSent)

            self.prePutMsg(event)
            event.succeed(delay=ticks)
            self.env.process(self._putdelay(event.item))

            if not self.firstActivity:
                self.firstActivity=self.env.now

            self._updatePutDebt(pkt)