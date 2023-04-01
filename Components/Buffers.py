from Components.BasicComponent import Component
from simpyExtensions.util import NewEvent, BufferPut, BufferGet, BufferPeek
from simpy.resources.store import Store, StorePut
from SimSettings import simTicksPerCycle
from statistics import mean

#---------------------------------------------------------------------------------
#Storage objects: Generic Buffer, FlowControlled Buffer, credit buffer
#---------------------------------------------------------------------------------
class Buffer(Component, Store):
    """ Generic class for a buffer that can be animated. It inherits from the Component class

        Class members:
            - capacity: indicating how deep the buffer is
            - putDelay: the delay taken (after space becomes available) before the packet being inserted
            into the buffer becomes available for reading.
            - getDelay: the delay taken (after a packet  becomes available) before the packet being inserted
            into the buffer becomes available for reading.
            - putBusy: a flag indicating whether the put method is currently in use
            - getBusy: a flag indicating whether the get method is currently in use
            - putBytesPerCycle: indicates how many bytes can be written into the buffer per tick
            - putBytesPerCycle: indicates how many bytes can be read from the buffer per tick
            - animate: a flag indicating whether the buffer is to be animated
            - other members used to gather statistics about the operation of the buffer

        Class methods:

            - __init__(): initiator function
                    usage: Buffer(env,'buff','blockname',capacity=4)
            - isFull():  returns True if the buffer is full
                    usage: buffer.isFull()
            - isEmpty(): returns True if the buffer is empty
                    usage: buffer.isEmpty()
            - OccupiedSlots(): a method that returns how many slots are available in the buffer
            - put(pkt): a method for inserting packets into the buffer (see put() code below for more info)
            - get(): a method for retrieving packets from the head of the buffer (see get() code below for more info)
            - peek(): a method that returns the packet at the head of the buffer, if any, without removing it.
            - addDelayBeforePut():returns the number of ticks to wait before packet start being inserted into the buffer
            - addDelayAfterPut():returns the number of ticks to wait after packet is inserted into the buffer before another packet can be put
            - addDelayBeforeGet():returns the number of ticks to wait before packet start being read from the buffer
            - addDelayAfterGet():returns the number of ticks to wait after packet is read from the buffer before another packet can be read
            - afterPutMsg(): helper to customize logging when a packet starts being written into the buffer
            - afterGetMsg(): helper to customize logging when a packet starts being read from the buffer
            - GetReady(): function to set the status of the get method to ready to be used

            """

    def __init__(self, env,
                       name,
                       parent=None,
                       info="",
                       capacity=1,
                       putBytesPerCycle=16,
                       getBytesPerCycle=16,
                       putDelay=0,
                       getDelay=0,
                       monitorBW=False,
                       monitorInterval=250,
                       animate=False,
                       canvas=None,
                       an_params=None):
        """initiator function. usage: Buffer(env,'buff','blockname',capacity=4)"""

        Component.__init__(self, env, name, parent)

        Store.__init__(self,env,capacity)
        self.peek_queue=[]
        self.putDelay=putDelay
        self.getDelay=getDelay
        self.putDebt=0
        self.getDebt=0
        self.putBytesPerCycle=putBytesPerCycle
        self.getBytesPerCycle=getBytesPerCycle
        self.fromUp = self
        self.fromDn = self
        self.putCalls=[]
        self.putTimes=[]
        self.getCalls=[]
        self.getTimes=[]


        self.timeSamples=[]
        self.monitorBW=monitorBW
        self.totalWrBits=0
        self.totalRdBits=0
        self.wrBw=[]
        self.rdBw=[]
        self.monitorInterval=monitorInterval* simTicksPerCycle
        self.lastActivity=0
        self.firstActivity=None

        self.animate=animate

        self.statistics={}
        self.statistics['inter_arrival_time']=0
        self.statistics['inter_departure_time']=0
        self.statistics['staytime']=0
        self.statistics['pktcount']=0
        if self.animate:
            self.slots=self.initUI()

    def run(self):

        if self.animate:
            self.env.process(self.update())
        
        if self.monitorBW:
            self.env.process(self.bwMonitor())

        yield self.env.timeout(1)

    def occupiedSlots(self,seg=None):

        return len(self.items)

    def isFull(self):
        """returns True if the buffer is full. usage: buffer.isFull()"""

        if self.occupiedSlots()==self.capacity:
            return True
        else:
            return False

    def isEmpty(self):

        """returns True if the buffer is Empty. usage: buffer.isEmpty()"""
        if self.occupiedSlots()==0:

            return True
        else:
            return False

    def availableSlots(self):

        return (self.capacity-self.occupiedSlots())

    def occMonitor(self):

        last_arrival=0
        last_departure=0
        while True:

            while self.putCalls and self.getCalls and \
                  self.putCalls[0].processed and  self.getCalls[0].processed:
                put=self.putCalls.pop()
                get=self.getCalls.pop()
                putTime=self.putTimes.pop()
                getTime=self.getTimes.pop()

                self.statistics['staytime']=round((self.statistics['staytime']*self.statistics['pktcount']+getTime-putTime)\
                        /(self.statistics['pktcount']+1),2)

                self.statistics['inter_arrival_time']=round((self.statistics['inter_arrival_time']*self.statistics['pktcount']\
                        +putTime-last_arrival)/(self.statistics['pktcount']+1),2)

                self.statistics['inter_departure_time']=round((self.statistics['inter_departure_time']*self.statistics['pktcount']\
                        +getTime-last_departure)/(self.statistics['pktcount']+1),2)

                self.statistics['pktcount']+=1
                lastArrival=putTime
                lastDeparture=getTime
            yield self.env.timeout(self.monitorInterval)

    def bwMonitor(self):

        lastTotalWrBits = 0
        lastTotalRdBits = 0
        bw_interval = 0


        while True:

            yield self.env.timeout(self.monitorInterval)
            self.timeSamples.append(self.env.now)

            bw_interval = (self.totalWrBits - lastTotalWrBits) / (self.monitorInterval)
            self.wrBw.append(bw_interval)
            lastTotalWrBits=self.totalWrBits

            bw_interval = (self.totalRdBits - lastTotalRdBits) / (self.monitorInterval)
            self.rdBw.append(bw_interval)
            lastTotalRdBits=self.totalRdBits

    def dumpBwVsTime(self):
        """this function dumps time series data about the writing bandwidth into the 
            buffer. The output is two lists:
                - time: a list of the timestamps indicating the end of intervals in which bandwidth is measured
                - wrBw: a list with the observed bandwidth at the write side of the buffer in each of the intervals given by time

            Note that the first element of each of the lists is a string prefix(empty by default) providing information for further   a tuple where data format is a list  of which the first element is a string giving 
            processing the actual data starts with index 1 of these lists instead of 0.

            The values are adjusted for the simTicksPerCycle so the time is in hardware cycles and the bandwidth is in Gbps"""

        prefix=''

        time= [prefix]+[t/simTicksPerCycle for t in self.timeSamples]
        wrBw= [prefix]+[bw*simTicksPerCycle for bw in self.wrBw]

        return time, wrBw

    def dumpStats(self):
        
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
        stats=[]
        maxbw=simTicksPerCycle*max(self.wrBw) if self.wrBw!=[] else 0
        firstActivity=self.firstActivity if self.firstActivity else 0
        lastActivity=self.lastActivity if self.lastActivity else 0
        totalBitsSent=self.totalWrBits
        activeDuration=(self.lastActivity-self.firstActivity) if self.firstActivity!=None else 0

        averagebw0=simTicksPerCycle*(totalBitsSent/activeDuration) if activeDuration  else 0
        averagebw1=simTicksPerCycle*(totalBitsSent/self.env.now)
        averagebw2=simTicksPerCycle*mean(self.wrBw) if self.wrBw else 0
        averagebw3=(simTicksPerCycle)*(self.monitorInterval*sum([b**2 for b in self.wrBw]))/totalBitsSent if totalBitsSent  else 0


        stats=[name,round(maxbw,2),round(averagebw0,2),round(averagebw1,2),round(averagebw2,2),round(averagebw3,2),totalBitsSent,int(firstActivity/simTicksPerCycle),int(lastActivity/simTicksPerCycle),int(self.env.now/simTicksPerCycle)]
        
        return stats

    def initUI(self):

        self.master.title("Buffer")
        self.pack(fill=BOTH, expand=1)

        direc=self.an_params['direction']
        x0=self.an_params['x0']
        y0=self.an_params['y0']
        x1=self.an_params['x1']
        y1=self.an_params['y1']

        if direc in ['N','S']:
            sloth=abs(y1-y0)/self.capacity
        else:
            sloth=abs(x1-x0)/self.capacity

        slots=[]

        y_shift= abs(y1-y0) if direc in ['W','E'] else sloth
        x_shift= abs(x1-x0) if direc in ['N','S'] else sloth
        x=x0
        y=x1

        for slot in range(self.capacity):

            if direc in ['N','E']:
                slots.append(self.canvas.create_rectangle(x,y, x+x_shift, y+y_shift, fill="white"))
            else:
                slots=[self.canvas.create_rectangle(x,y, x+x_shift, y+y_shift, fill="white")]+slots

            x+=x_shift if direc in ['E','W'] else 0
            y+=y_shift if direc in ['N','S'] else 0

        self.canvas.pack(fill=BOTH, expand=1)
        return slots

    def update(self):

        while True:

            for slot in range(len(self.store.items)):
                self.canvas.itemconfig(self.slots[slot], fill='red')
                self.canvas.update()
            for slot in range(len(self.store.items),self.capacity):
                self.canvas.itemconfig(self.slots[slot], fill='white')
                self.canvas.update()

            yield self.env.timeout(1)


    def put(self,item,caller=None):

        """a method that waits until there is space in the buffer and adds a packet to its tail.
            usage packet=yield buffer.put(pkt). The steps are as follows:
                1- Check if another put() call is in progress, if so, throw an exception
                2- if no other put() call is ongoing, set put process as busy to prevent other put calls while
                    the current one is being served
                3- Instantiate a BufferPut() event (check the documentation of the BufferPut class)
                    and append to its callbacks the buffer method to bring the putprocess into the ready state.
                4- The callback flagging the put method as ready will be activated only after the following happening sequentially:
                    a) a space becomes available in the buffer
                    b) the time returned by self.addDelayBeforePut() function, if any, passes
                    c) the packet actually inserted into the buffer (instantaneous)
                    d) the time returned by self.addDelayAfterPut() function, if any, passes
                   If addDelayBeforePut() and addDelayAfterPut() return 0, then the only waiting time is for a space to become available
                   in the buffer.
                5- finally the method returns the BufferPut event
            """
        return BufferPut(self,item,caller)

    def addPrePutDelay(self, item):
        """ This function adds a put delay before an item is actually appended into
         the store. When yield store.put(item) is called, the following will happen:
             1- block waiting a space to become available
             2- block for the number of ticks returned by this function
             3- append the item the store (store.items.append(item))
             4- block until the number of ticks returned by addDelayAfterPut(), if any
             5- unblock and return the item"""


        return self.putDelay*simTicksPerCycle
    
    def addPostPutDelay(self,item):

        ticks,debt=item.getTicks(self.putBytesPerCycle)
        ticks+=int(self.putDebt+debt)
        return ticks*simTicksPerCycle

    def postPutMsg(self, item):

        """ This function adds a put delay after an item has been inserted out
        into the store. When yield store.put(item) is called, it will only
        unblock only after:
             1- the item has been actually inserted into the store, ie, store.items.append(item)
            THEN;
             2- the number of ticks returned by this function has passed"""

        self.Log('INFO', "Started writing packet {} into the buffer. This will take {} ticks".format(item.uid,self.addPostPutDelay(item)))

    def _do_put(self, event):

        if len(self.items) < self._capacity:
            preputdelay=self.addPrePutDelay(event.item)
            postputdelay=self.addPostPutDelay(event.item)
            event.callbacks.append(self._updateTotalWrBits)

            if preputdelay:
                ev=NewEvent(self.env,item=event.item)
                ev.callbacks+=[self._insert_packet,self._trigger_get,self._trigger_peek]
                ev.succeed(delay=preputdelay)
                event.succeed(delay=postputdelay)

            else:
                event.succeed(delay=postputdelay)
                self._insert_packet(event)
                self._trigger_get(None)
                self._trigger_peek()

            self.lastActivity=self.env.now+postputdelay

            self._updatePutDebt(event.item)

            if self.firstActivity==None:
                self.firstActivity=self.env.now

        return None


    def _insert_packet(self,event):

        self.items.append(event.item)

        self.postPutMsg(event.item)

    def _putBusy(self,*args):

        if self.isFull():
            self.Log('FATAL_ERROR', "Trying to write into the buffer while full")

        if self.env.now<self.lastActivity:
            self.Log('FATAL_ERROR', "Trying to write into the buffer while another write is ongoing")

    def _updatePutDebt(self,item):
        ticks,debt=item.getTicks(self.putBytesPerCycle)
        self.putDebt=(self.putDebt+debt)-int(self.putDebt+debt)

    def _updateTotalWrBits(self,event):
        
        self.totalWrBits += event.item.getBytes()*8


    def get(self,item=None,caller=None):
        """a method that waits until the buffer is not empty and returns the packet at its head.
            usage:- blocking: packet=yield buffer.get()
                  - non-blocking: getcall=buffer.get()

                The steps are as follows:

                1- Check if another get() call is in progress, if so, throw an exception
                2- if no other get() call is ongoing, set put process as busy to prevent other get calls while
                    the current one is being served
                3- Instantiate a BufferGet() event (check the documentation of the BufferGet class)
                    and append to its callbacks the buffer method to bring the get process into the ready state.
                4- The callback flagging the get method as ready will be activated only after the following happening sequentially:
                    a) The buffer becomes non-empty
                    b) the time returned by self.addDelayBeforeGet() function, if any, passes
                    c) the packet actually popped out of the buffer (instantaneous)
                    d) the time returned by self.addDelayAfterGet() function, if any, passes
                   If addDelayBeforeGet() and addDelayAfterGet() return 0, then the only waiting time is for a packet to become available
                   in the buffer.
                5- finally the method returns the BufferGet event

           Note that this method does not return a packet, it just simulates the time necessary for a packet to be read
           to actually get the packet at head, use the peek() method.

           Usage in store-and-forward mode:
                    pkt=yield buffer.peek()
                    yield self.env.process(buffer.get())
                    {
                        processing pkt and/or start forwarding downstream
                    }

            Usage in cut-through mode:
                    pkt=yield buffer.peek()
                    {
                        processing pkt and/or start forwarding downstream
                    }
                    yield self.env.process(buffer.get())

        """
        if caller:
            self.Log("DEBUG","Read request initiated by {}".format(caller.name))
        else:

            self.Log("DEBUG","Read request initiated")

        return BufferGet(self,item,caller)

    def addPreGetDelay(self, item):
        """ This function adds a get delay after an item has been poped out
        of the store. When yield store.get() is called, it will only
        unblock only after:
             1- the item has been popped out of the store, ie, store.items.pop(0)
             2- the number of ticks returned by this function has passed"""

        return self.getDelay*simTicksPerCycle

    def addPostGetDelay(self, item):
        """ This function adds a get delay after an item has been poped out
        of the store. When yield store.get() is called, it will only
        unblock only after:
             1- the item has been popped out of the store, ie, store.items.pop(0)
             2- the number of ticks returned by this function has passed"""

        ticks,debt=item.getTicks(self.getBytesPerCycle)
        return ticks*simTicksPerCycle

        # return item.getTicks(self.getBytesPerCycle)*simTicksPerCycle

    def postGetMsg(self, item):

        """ This function adds a get delay after an item has been poped out
        of the store. When yield store.get() is called, it will only
        unblock only after:
             1- the item has been popped out of the store, ie, store.items.pop(0)
             2- the number of ticks returned by this function has passed"""

        self.Log( 'INFO', "Started reading packet {} from the buffer. This will take {} ticks".format(item.uid,self.addPostGetDelay(item)))

    def _do_get(self, event):

        if self.items:

            item=self.items[0]
            pregetdelay=self.addPreGetDelay(item)
            if pregetdelay:
                event.callbacks+=[self._remove_packet,self._trigger_put,self._updateTotalRdBits]
                event.succeed(item,delay=pregetdelay)

            else:
                event.callbacks+=[self._trigger_put,self._updateTotalRdBits]
                self._remove_packet(event)
                event.succeed(item,delay=pregetdelay)

            self._updateGetDebt(item)

        return None

    def _remove_packet(self,event):

        item=self.items.pop(0)
        self.postGetMsg(item)

    def _updateTotalRdBits(self,event):
        
        self.totalRdBits += event.value.getBytes()*8

    def _updateGetDebt(self,item):

        ticks,debt=item.getTicks(self.getBytesPerCycle)
        self.getDebt=(self.getDebt+debt)-int(self.getDebt+debt)



    def peek(self, item=None,caller=None):

        if caller:
            self.Log("DEBUG","Peek request initiated by {}".format(caller.name))
        else:

            self.Log("DEBUG","Peek request initiated")

        return BufferPeek(self, item, caller)

    def _trigger_peek(self,*args) -> None:
        """Trigger peek events.

        This method is called once a new peek event has been created or a put
        event has been processed.

        The method iterates over all put events in the :attr:`put_queue` and
        calls :meth:`_do_peek` to check if the conditions for the event are met.
        If :meth:`_do_peek` returns ``False``, the iteration is stopped early.
        """

        # Maintain queue invariant: All peek requests must be untriggered.
        # This code is not very pythonic because the queue interface should be
        # simple (only append(), pop(), __getitem__() and __len__() are
        # required).
        idx = 0
        while idx < len(self.peek_queue):
            peek_event = self.peek_queue[idx]
            proceed = self._do_peek(peek_event)
            if not peek_event.triggered:
                idx += 1
            elif self.peek_queue.pop(idx) != peek_event:
                raise RuntimeError('Peek queue invariant violated')

            if not proceed:
                break

        return None

    def _do_peek(self, event):

        if self.items:

            event.succeed(self.items[0])

        return None

class FlowControlledBuffer(Buffer):
    """ Generic class for a buffer that can be animated.

        Class members:
            - capacity: indicating how deep the buffer is
            - store: a simpy store of the same capacity as the capacity
            - putdelay: the delay taken to write into the buffer when space permits
            - getdelay: the delay taken to read out from the buffer
            - putarb: a simpy resource used to make sure only a single entity can put packets
            in the buffer at any time
            - getarb: a simpy resource used to make sure only a single entity can get packets
            from the buffer at any time
            - animate: a flag indicating whether the buffer is to be animated
            - other members used to gather statistics about the operation of the buffer

        Class methods:
            - __init__(): initiator function
                    usage: Buffer(env,'buff','blockname',capacity=4)
            - isFull():  returns True if the buffer is full
                    usage: buffer.isFull()
            - isEmpty(): returns True if the buffer is empty
                    usage: buffer.isEmpty()
            - get(): a blocking method that waits until the buffer is not empty and returns the packet at its head.
                    usage packet=yield self.env.process(buffer.get())
            - put(packet): a blocking method that waits the buffer has space and inserts the packet to the tail.
                    usage: yield env.process(buffer.put(packet))
            - peek(): a non-blocking method that returns the packet at the head of the buffer, if any, without removing it.
                    usage: buffer.peek()


            """

    def _remove_packet(self,event):

        item=self.items.pop(0)
        self.postGetMsg(item)
        self.toUp.putCredit()

class StoreAndForwardBuffer(Buffer):

    def addPrePutDelay(self, item):

        ticks,debt=item.getTicks(self.putBytesPerCycle)
        ticks+=int(self.putDebt+debt)
        return (ticks+self.putDelay)*simTicksPerCycle

    def addPostPutDelay(self, item):

        ticks,debt=item.getTicks(self.putBytesPerCycle)
        ticks+=int(self.putDebt)
        return ticks*simTicksPerCycle

class CreditBuffer(Component, Store):

    def __init__(self,env,name='',parent=None, initCredits=4):

        Component.__init__(self, env, name, parent)
        Store.__init__(self,env,initCredits)
        self.peek_queue=[]
        self.items=[1]*initCredits

    def put(self,item):

        storePut=StorePut(self,item)
        storePut.callbacks.append(self._trigger_peek)

        return storePut

    def peek(self,thresh=1):

        return BufferPeek(self,thresh)

    def _trigger_peek(self,*args) -> None:
        """Trigger peek events.

        This method is called once a new peek event has been created or a put
        event has been processed.

        The method iterates over all put events in the :attr:`put_queue` and
        calls :meth:`_do_peek` to check if the conditions for the event are met.
        If :meth:`_do_peek` returns ``False``, the iteration is stopped early.
        """

        # Maintain queue invariant: All peek requests must be untriggered.
        # This code is not very pythonic because the queue interface should be
        # simple (only append(), pop(), __getitem__() and __len__() are
        # required).

        idx = 0
        while idx < len(self.peek_queue):
            peek_event = self.peek_queue[idx]
            proceed = self._do_peek(peek_event)

            if not peek_event.triggered:
                idx += 1
            elif self.peek_queue.pop(idx) != peek_event:
                raise RuntimeError('Peek queue invariant violated')

            if not proceed:
                break

        return None

    def _do_peek(self, event):

        if len(self.items)>event.item:
            #check if the number of available credit is greater than or equals the threshold indicated by event.item
            event.succeed()
            return True
        return None
