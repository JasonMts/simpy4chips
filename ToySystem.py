from Components.BasicComponent import Component
import logging
import SimSettings
import simpy
from simpy import AllOf, Event

class Component(object):
    """Base class for all components that collects common member vars and implements common logging

    All components inherit from this class which confers the following member variables:

       * parentname : the entities hierarchical simulation path name
       * name: the name of the object
       * fullname : the concatenation of the above two
       * config: a dictionary of configurable variables representing registers
       * action: a simpy function that is invoked when simpy.run is called from the simulation toplevel.
       by default this method completes after one timetick but in the other specifict components 
              they invoke all the simpy processes for that component.

    In addition this class provides the common logging infrastructure for the simulation

    Arguments:
        env (simpy.Environment) : the handle to the Simpy simulation environment
        name (string)           : the name of the object
        parentname (string)     : the full hierarchical name of the parent object
        config (dict)           : see comments above"""

    packet_record_files = None
    

    def __init__(self, env, name, parentname, config=None):

        self.env = env
        self.name = name
        self.parentname = parentname
        self.fullname = parentname + "/" + name
        self.config = config
        self.action = self.env.process(self.run())

    @classmethod
    def SetPktFilter(cls, pktfilterval):
        """Sets the packet filter class variable that enables info message suppression"

        Define a packet uid. If the pktfilter is not None then all packet related info messages from
        packets with a uid that does not match the filter will be suppressed"""

        cls.pktfilter = pktfilterval

    @classmethod
    def EnablePacketRecording(cls, filelist):
        cls.packet_record_files = filelist
        for colossus in filelist:
                cls.packet_record_files[colossus][0].write("<root>\n  <packets>")
                cls.packet_record_files[colossus][1].write("<root>\n  <packets>")

    def record_packets(cls, simtime, pktlist, pkttype, in_n_out, instname, parentname):
        fh = Newsim.packet_record_files[parentname][in_n_out]

        for pkt in pktlist:
            fh.write("    <%s time=\"%d\", dir=\"%d\", block=\"%s\", type=\"%s\", srcipudid=\"%s\", srctileid=\"%s\", bcbitmap=\"%s\", desttileid=\"%s\", readlength=\"%s\", size=\"%s\"/>"  %(
                pkttype, simtime, in_n_out, instname, pkt.type, pkt.srcipuid, pkt.srctileid, format(pkt.bcbitmap, '#018b'), pkt.tileid, pkt.readlength, pkt.size))


    def run(self):
        """Dummy simpy run function for the base class; completes after one time tick"""

        yield self.env.timeout(1)

    def Log(self, msgtype, msg, pkt=None, infolist=None):
        """Common logging function used by all descendents of Component base class

        Arguments:
           msgtype(string) : One of 'INFO', 'WARNING', 'CONFIG_ERROR', 'FATAL_ERROR'
           msg(string)     : The message to be logged, specified by the Newmanry object
           pkt(PktHdr)     : Packet related messages may pass the packet concerned in order to enable
                             packet info message filtering
           infolist(list)  : Some messages may pass this list of strings as arbitrary additional debug
                             info to be logged"""

        # construct the output from the current sim time, objects full pathname and the passed message
        fullmsg = '[@%d]%s : %s' % (self.env.now, self.fullname, msg)
        displayinfo = True

        # determine whether output should be suppressed based on packet filter argument
        if self.pktfilter:
            # suppression only applies to Log() calls which also pass a packet object as an argument
            if pkt is not None:
                if pkt.uid != self.pktfilter:
                    displayinfo = False

        # always output the message if it is an error message or warning
        if msgtype == 'FATAL_ERROR' or msgtype == 'CONFIG_ERROR':
            logging.info(fullmsg)
        elif msgtype == 'WARNING':
            logging.warning(fullmsg)
        elif msgtype == 'INFO':
            # info messages can be suppressed according to packet id
            if displayinfo:
                logging.info(fullmsg)
        else:
            raise RuntimeError("Newsim.log: Unsupported message type [%s] in %s " % (msgtype, self.fullname))

        # some messages pass a list of strings which provides more debug info relating to the message
        # if this argument is present, print out the strings (unless message is being suppressed)
        if infolist and displayinfo:
            logging.info("\tInfodump follows:")
            for item in infolist:
                logging.info("\t%s" % item)

        # finally, if the message was an error, raise an exception.
        if msgtype is 'FATAL_ERROR' or msgtype is 'CONFIG_ERROR':
            raise RuntimeError(fullmsg)

class IgPort(Component):

    """Ingress Port Class containing an elastic buffer and credit buffer

    Arguments (in addition to Component constructor args):
        depth(int)    : The depth of the buffer in packets
        occwarn(bool) : If this is True then a warning will be printed (once)
                        when/if the buffer reaches maximum occupancy, and
                        occupancy stats gathering will be enabled

       This object is vital to the simulation structure. It consists of three
       stores: ingress, ingress_tail and pipeline. The first two stores are
       intended to be written to via put() methods called from an EgPort object.

       That is, a simpy process in a Newmanry object will put a packet to an
       EgPort, and then the EgPort object will write the packet to the IgPort.

       Packets are split into headers, and the tail, representing the payload. 
       This is done in order to model cut through Behaviour in the buffers; 
       an entity getting from the IgPort can obtain the header and process/route 
       it before the tail arrives, just like in the real hardware. 
       Then, having obtained the header it can wait for the tail before continuing. 
       This model works as long as packets are presumed to not have
       gaps in them.

       The pipeline store is used to model a fixed pipeline delay into which all the
       relevant pipeline delays of the parent block are lumped. The
       run_pipe() process starts a new Simpy Process (latency() for each packet
       which just waits a number of timeticks equal to self.pipedelay and then
       puts the packet to the pipeline store. A maximum of n latency processes will
       be active at any one time where n = self.pipedelay
       """

    def __init__(self, env, name, parentname, depth=1, occwarn=True):
        Component.__init__(self, env, name, parentname)


        self.depth = depth
        self.occwarn = occwarn
        self.packets_in_pipe=0
        self.warned = False

        # number of cycles delay each packet experiences as it passes through

        self.pipedelay = 2

        # defines the sampling interval in time ticks at which buffer occupancy
        # stats are gathered, if enabled.

        self.monitor_interval = 200
        self.stats = {}
        self.stats['occupancy']  = []
        self.stats['sampletimes'] = []

        self.ingress = simpy.Store(self.env, capacity=depth) #a store for the headers of the packets
        self.ingress_tail = simpy.Store(self.env, capacity=depth) #a store for the payloads of the packets
        self.pipeline = simpy.Store(self.env, capacity=depth) # a store for the processed headers (includes pipeline delays)


    def run(self):
        """Activates simpy processes for the IgPort"""

        if self.occwarn:
            self.env.process(self.run_monitor())

        yield self.env.process(self.run_pipe())

    def run_pipe(self):

        """Mimics the pieline delay"""

        while True:

            if self.occwarn and not self.warned:
                if len(self.pipeline.items) == self.depth:
                    print("Warning, @%dbuffer %s in %s is full" %(self.env.now, self.name, self.parentname))            
                    Newsim.Log(self, "WARNING", "buffer %s in %s is full" % (self.name, self.parentname))
                    self.warned = True

            pkt = yield self.ingress.get() #get a packet (header to start processing it) from the ingress buffer xib

            self.env.process(self.latency(pkt)) 

    def latency (self, pkt):
        """ A non blocking process which moves a packet from A to B in two cycles.
        Multiple instances of this process may be active at once."""

        yield self.env.timeout(self.pipedelay*SimSettings.simTicksPerCycle) #simulate the delay to process the packet header

        yield self.pipeline.put(pkt) # put the packet ready to be send on EgPort

    def put_hdr(self, pkt):
        "External method used to write a packet header to the IgPort"
        return  self.ingress.put(pkt)

    def put_tail(self):
        "External method used to write a packet tail to the IgPort"
        return self.ingress_tail.put("tail")

    def get_hdr(self):
        "External method used to get a packet header from the IgPort"

        return self.pipeline.get()

    def get_tail(self):
        """Get a get a packet tail from the buffer.

        There is a bug here since the tails dont go through the pipeline delay.
        For sims where all packets are the same size this should not matter but
        it ought to be fixed"""

        return self.ingress_tail.get()

    def run_monitor(self):
        """Simpy process to gather buffer occupancy stats. Only runs if
        self.occwarn=True"""
        
        while True:
            yield self.env.timeout(self.monitor_interval)
            self.stats['sampletimes'].append(self.env.now/NewmanConstants.TIMEBASE)
            self.stats['occupancy'].append(len(self.pipeline.items))

class EgPort(Component):
    """EgPorts are paired with IgPorts via a reference

    Arguments:
        link(IgPort):  The IgPort object to which the EgPort is linked.
                       For example, a TR EgPort object representing that
                       TR's Exchange Egress SOuth port would link to
                       an IgPort in an XB.
        enabled(bool): EgPorts can be disabled where they are not connected
                       to anything (dangling) in the real hardware so as to
                       catch packets which have been routed to them"""


    def __init__(self, env, name, parentname, link=None, enabled=False):
        Component.__init__(self, env, name, parentname)
        self.link = link
        self.enabled = enabled

    def run(self):
        """Dummy run process for the EgPort"""

        yield self.env.timeout(1)

    def put(self, pkt):
        """Write a packet to an egress port.

        The packet is not buffered here, it is buffered in the linked IgPort.
        It is not necessary to separately put headers and tails to an EgPort."""

        if self.enabled:
            # put the packet header

            yield self.link.put_hdr(pkt)
            # timeout for time taken to send payload
            yield self.env.timeout(pkt.size * NewmanConstants.TIMEBASE)

            #send a 'weightless' tail marker.
            yield self.link.put_tail()

        else:
            Component.Log(self, 'CONFIG_ERROR', "Disabled Port received packet .\
                              %s. Packet history follows:" %(pkt), pkt=pkt, info=pkt.history)

    def check_link(self):
        """Checks that the EgPort is linked to an IgPort instance and not left dangling"""

        if self.enabled and (not isinstance(self.link, IgPort)):
            Component.Log(self, 'CONFIG_ERROR', " Egress Port mis-connected to this: %s" % self.link)
            return 0
        else:
            return 0

    def __repr__(self):
        return "%s".\
            format(self.fullname)

class Router(Component):

    """Class for a Router

    Models a single Router of packets with multiple ingress and egress ports.
    
    This Router runs 2 parralel traffic lanes:
        - One of them carry traffic clockwise around a ring (lane a)
        - One of them carry traffic anti-clockwise around a ring (lane b)

    a single lane is formed by:
        - an IgPort to receive traffic from attached Router
        - an EgPort to forward packet to the next router
        - an arbiter to regulate access to the EgPort between packets from the attached router and the attached processor

    Traffic incoming onto a router may egress to the attached processor. In addition to the EgPorts leading to another Router,
    each direction (cw and ccw) has a dedicated egport statically configured to forward packets from one of the two lanes.
    So packets incoming from another router can either proceed to the next router or egress to the attached processor. 

    The attached block can also send packets to join one of the two lanes. For that it uses one IgPort per lane.

    Before each IgPort that connects to another Router, there is an arbiter that arbiters between packets from the attached processor and
    packets from another router. These arbiters are simpy resources. 

    """


    def __init__(self, env, name, parentname, config):

        Component.__init__(self, env, 'Router_' + name, parentname, config=None)

        # External Ports
        self.routerid=None
        self.igports = {}
        #Ports that receive packets from two other Routers (two lanes a, b per remote router 0,1): 
        self.igports['ria'] = IgPort(env, "ria", self.fullname, depth=3)
        self.igports['rib'] = IgPort(env, "rib", self.fullname, depth=3)

        #Ports that receive packets from an attached block that sends packets on two of its ports (n for north and s for south)
        self.igports['pia'] = IgPort(env, "pia", self.fullname, depth=3)
        self.igports['pib'] = IgPort(env, "pib", self.fullname, depth=3)

        self.egports = {}

        #Ports that send packets to two other Routers (two ports a, b per remote router 0,1): 
        self.egports['rea'] = EgPort(env, "rea", self.fullname, enabled=True)
        self.egports['reb'] = EgPort(env, "reb", self.fullname, enabled=True)

        #Ports that send packets to an attached block that receives packets on two of its ports (n for north and s for south)
        self.egports['pea'] = EgPort(env, "pea", self.fullname, enabled=True)
        self.egports['peb'] = EgPort(env, "peb", self.fullname, enabled=True)

        # EgPorts arbiters
        # Packets that go on EgPorts that connect to other router can be from the block attached to that router or packets 
        #forwarded from another router hence an arbitration is required between these two sources one arbiter per EgPort

        self.arbrea = simpy.PriorityResource(env, capacity=1)
        self.arbreb = simpy.PriorityResource(env, capacity=1)

    def check_conns(self):
        """private method: check that all Router EgPorts are connected to a valid IgPort object"""

        clok = self.egports['rea'].check_link()
        clok = clok or self.egports['reb'].check_link()
        clok = clok or self.egports['pea'].check_link()
        clok = clok or self.egports['peb'].check_link()

        if clok:
            raise RuntimeError("%s has misconnected egress links", self)

    def connect(self, srcport, desttr, destport):
        """helper method to connect the Router to Router ports

        Arguments:
            srcport(bool)       : connect from the south(false) or north(true) port of this Router
            desttr(Router)      : the Router to wire this Router EgPorts to
            destport(bool)      : connect to the south(false) or north(true) port of the
                                  destination Router"""

        if srcport:
            srcports = ['te1a', 'te1b']
        else:
            srcports = ['te0a', 'te0b']
        if destport:
            destports = ['ti1a', 'ti1b']
        else:
            destports = ['ti0a', 'ti0b']

        for p in range(4):
            self.egports[srcports[p]].link = desttr.igports[destports[p]]

    def run(self):


        """simpy run process for the Router which runs the per IgPort sub-process to handle packets and forward them.

        This is kicked of by simpy automatically upon run().

        First it checks that all the TR ports are connected to something valid then the following processes
        are started:

            run_frombouter()  : one of these runs for each of the 4 paths in the router that sees packets received from another Router. 
                                They manage data incomin to a buffer from the neighbouring router or loopback and arbitrate for their
                                 matched 

            run_fromblock() :  one of these runs for each of the buffers in the router that receive packets from the attached block. They manage data
                            incoming to a buffer from an attached block and arbitrate for all router EgPorts"""

        self.check_conns()

        # instantiate port 0 tibs and port 1 xib (all pointing to port1)
        self.env.process(self.run_fromrouter
                         (self.igports['ri0a'], self.egports['re1a'], self.egports['bes'],
                          self.arbre1a, 0, NewmanConstants.TREG_LANEA)
                        )

        self.env.process(self.run_fromrouter
                         (self.igports['ri0b'], self.egports['re1b'], self.egports['bes'],
                          self.arbre1b, 0, NewmanConstants.TREG_LANEB)
                        )

        self.env.process(self.run_fromblock
                         (self.igports['bin'], 1,
                          [self.egports['re1a'], self.egports['re1b']],
                          [self.arbre1a, self.arbte1b],
                         )
                        )


        # instantiate port 1 tibs and port 0 xib (all pointing to port0)
        self.env.process(self.run_fromrouter
                         (self.igports['ri1a'], self.egports['re0a'], self.egports['ben'],
                          self.arbre0a, 1, NewmanConstants.TREG_LANEA)
                        )

        self.env.process(self.run_fromrouter
                         (self.igports['ri1b'], self.egports['re0b'], self.egports['ben'],
                          self.arbre0b, 1, NewmanConstants.TREG_LANEB)
                        )

        yield self.env.process(self.run_fromblock
                               (self.igports['xis'], 0,
                               [self.egports['re0a'], self.egports['re0b']],
                               [self.arbre0a, self.arbte0b],
                               )
                              )
        
    def egress_routing_match (self, packet, lane, egrr):
        """private method for the TR to evaluate whether there is an egress routing match for a given packet
        
            a TR will forward a northgoing (southgoing) packet, ie entering the TR via TIS (TIN) onto XES (XEN) if:
                        1) the packet is on the lane specified by EGRN(S)R.EGLANE
                        2) there is a routing match between the packet's bcbm and EGRN(S)R.IPUBM
                        3) if there is a tileid match (in case of TRs connected to XBs, ie if TILEIDMEN=1

        Arguments:
            packet(ElPktHdr) : The packet to be inspected for match
            lane(int)        : which lane is the packet on? 0:lane A, 1: lane B etc
            egrr(string)     : the TR egrr control register that presides over the match"""

        tileid = (packet.tileid & 0x38) >> 3 # the destination XB number
        
        tileid_1h = 1 << tileid #one-hot encoding of the destination XB number
        bcbm = packet.bcbitmap # the broadcast bitmap of the packet
        match = False
        tilematch = False
        ipumatch = False


        tilebm = getbyname(self.config, egrr, 'TILEBM') 
        ipubm = getbyname(self.config, egrr, 'IPUBM')
        ipumen = getbyname(self.config, egrr, 'IPUMEN')
        tilemen = getbyname(self.config, egrr, 'TILEMEN')
        cfglane = getbyname(self.config, egrr, 'EGLANE')
        

        if packet.type == NewmanConstants.EPWR or packet.type == NewmanConstants.EPRD:
            if getbyname(self.config, egrr, 'PCIEG'): #if this is a packet to host, check whether this is a PCI egress port
                match = True
                if cfglane != lane: #only egress if the TR ingress lane matches the EGLANE of the Egress routing register
                    Newsim.Log(self, 'CONFIG_ERROR',
                               "PCI egress packet %s for PCI egress on lane %d (should be on lane==0/A)" % (
                               packet, lane), packet
                              )
        elif lane == cfglane:
            if tileid_1h & tilebm:
                tilematch = True
            if bcbm & ipubm:
                ipumatch = True
            if ipumen:
                if tilemen:
                    match = tilematch & ipumatch
                else:
                    match = ipumatch
            elif tilemen:
                match = tilematch
            else:
                match = False


        return match

    def run_fromrouter(self, northgoing, lane):

        """simpy generator for Trunk Ingress Buffer in Trunk Router
        
        - router port (boolean): indicates the direction of the traffic (True:South-going, False:Northgoing)
        - tigport (IgPort): 
        - tegport (EgPort):
        - xegport (EgPort):
        - tegarb

        This function runs throughout the simulation and performs the following sequence:

        Prior to the forever loop:
           1. reads the relevant config regs to local variables
           2. checks its egport is connected to an igport

        In the forever loop:
            1. gets a packet from the TIB / pts = yield tigport.get_hdr()
            2. checks packet to see if tr hopcount limit of 20 is exceeded
            3. check for an egress routing match for the packet obtained in (1)
                3.1 if there is a match and ipu matching is enabled, remove the ipu id of the local
                ipu from the packet bcbitmap, otherwise leave the bitmap alone (e.g. in the case)
                of a tile match but no ipu match.
                3.2 determine if there are still bcbitmap bits set
            4a. If the packet still has bcbitmap bits set then create a new packet by passing the
                existing packet as an initiliaser to the constructor of ElPktHdr, which forms a packet
                for egress to the attached block with a uid decorated by 'eg', for egress. Then, put
                the newly formed egress packet to the exchange egress port and the existing packet with
                modified bcbitmap to the trunk egress port
            4b. If the packet has no bcbitmap bits set after subtracting the local ipuid, just put
                it to the exchange egress port
            4c. If there was no egress routing match put the whole packet unchanged to the trunk egress
                port
            4d. throw an error
            5. all the steps above just put the packet header. Now, need to wait for the tail to arrive
            before going round the loop again; this is part of the cut through modeling"""
        
        rigport=self.igports['ri'+('0' if northgoing else '1')+('a' if lane else 'b')]
        regport=self.egports['re'+('0' if northgoing else '1')+('a' if lane else 'b')]
        begport=self.egports['re'+('n' if northgoing else 's')]

        while True:
            # get first packet in tib
            pts = yield rigport.get_hdr()


            if self.egress_routing_match(pts, lane, egrr):

                #adjust bitmap and put the packet to the adapter egress port
                if egrripumen:
                    bitmap_egress = pts.bcbitmap & egrrbm
                    bitmap_onward = bitmap_egress ^ pts.bcbitmap
                else:
                    bitmap_egress = pts.bcbitmap
                    bitmap_onward = 0
            else :
                bitmap_onward = pts.bcbitmap
                bitmap_egress = 0

            # 4a: packet splits and goes to egress and opposite trunk port
            if bitmap_egress > 0 and bitmap_onward > 0:
                pts_egress = ElPktHdr(self.env, initialiser=pts, uid_decorator='x')                
                pts_egress.bcbitmap = bitmap_egress
                pts.bcbitmap = bitmap_onward

                with tegarb.request(priority=1) as req:
                    Newsim.Log(self, 'INFO', "TIB %s sent packet %s to exchange egress port %s and to opposing trunk (ipubm is %x, tilebm is %x)" % (tigport.name, pts, xegport.name, egrrbm, egrrtilebm), pkt=pts)
                    yield req
                    yield AllOf (self.env, [self.env.process(tegport.put(pts)), self.env.process(xegport.put(pts_egress))])

            # 4b: packet goes just to egress
            elif bitmap_egress:
                Newsim.Log(self, 'INFO', "TIB %s sent packet %s to exchange egress port %s (ipubm is %x, tilebm is %x)" % (tigport.name, pts, xegport.name, egrrbm, egrrtilebm), pkt=pts)
                yield self.env.process(xegport.put(pts))

            # 4c: packet goes just to trunk port
            elif bitmap_onward:
                with tegarb.request(priority=1) as req:
                    Newsim.Log(self, 'INFO', " TIB %s sent packet %s to opposing trunk (ipubm is %x, tilebm is %x, lane is %d)" % (tigport.name, pts, egrrbm, egrrtilebm, cfglane), pkt=pts)
                    yield req
                    yield self.env.process(tegport.put(pts))

            # 4d: something has gone badly wrong; this should never happen.
            else:
                Newsim.Log(self, 'FATAL_ERROR', "Packet %s matched neither egress to xe port nor onward routing" % (pts), infolist=pts.history)

            yield tigport.get_tail()

    def run_fromblock(self, xigport, portnum, tegports, arbs):
        """simpy generator for Exchange Ingress Buffer in Trunk Router

        This function runs throughout the simulation and performs the following sequence:

        Prior to the forever loop:
            1. reads the relevant config regs to local variables. This TR is either allowed to
               match for tile id routing, or not.
            2. if tile id routing is enabled, it is enabled just for north or for south. Either way,
               the IGLRR register will yield a lane to put the packet on depending on bits 5:3 of its tileid.


        In the forever loop:
            3. get the next packet in the XIB (blocking)
            4. split out bits 5:3 of the packets tileid
            5a. if tile id matching is enabled for this direction select the lane according to the IGLRR
            5b. if tile if matching is not enabled, select the lane according to the NOMNATCHEN field
                of the IGLRR, but only if the NOMATCHEN bit of the IGLRR is set
            5c: If neither 5a nor 5b applies, throw an error
            6. If either 5a or 5b applies, arbitrate for the determined TR egress lane then:
                6.1: wait to be granted by the arbiter
                6.2: put the packet header to the egport
                6.3: wait for the tile to arrive before repeating the forever loop

        """
        matchen = None
        # step 1
        if portnum:
            matchen = getbyname(self.config, 'XIGLRR', 'NTILEMEN')
        else:
            matchen = getbyname(self.config, 'XIGLRR', 'STILEMEN')

        # step 2
        lane_tid = [
            getbyname(self.config, 'XIGLRR', 'TID0LANE'),
            getbyname(self.config, 'XIGLRR', 'TID1LANE'),
            getbyname(self.config, 'XIGLRR', 'TID2LANE'),
            getbyname(self.config, 'XIGLRR', 'TID3LANE'),
            getbyname(self.config, 'XIGLRR', 'TID4LANE'),
            getbyname(self.config, 'XIGLRR', 'TID5LANE'),
            getbyname(self.config, 'XIGLRR', 'TID6LANE'),
            getbyname(self.config, 'XIGLRR', 'TID7LANE')
        ]

        enabled=getbyname(self.config, 'CSR', 'TREN')

        while True:
            # step 3: get first packet in aib
            pts = yield xigport.get_hdr()
            pts.history.append(self.fullname)
            if not enabled:
                Newsim.Log(self, 'CONFIG_ERROR', "Trunk Router %s received a packet %while disabled" % (self.name, pts), infolist="TREN = %x" % enabled)

            # step 4: get bits 5:3 of the tile id

            lane = None

            if pts.type == 1 or pts.type == 2:
                lane = getbyname(self.config, 'XIGLRR', 'LANEPCI')
                Newsim.Log(self, 'INFO', " XIB %s got packet %s, pciaddress is %x lane is %d" % (xigport.name, pts, pts.pciaddress, lane), pts)

            elif matchen:
                tileid53 = (pts.tileid & 0x38) >> 3

                #step 5a
                lane = lane_tid[tileid53]
                Newsim.Log(self, 'INFO', " XIB %s got packet %s, matchen is %d, tileid is %d, tileid53 is %d, lane is %d" % (xigport.name, pts, matchen, pts.tileid, tileid53, lane), pts)

            else:
                #step 5b
                if getbyname(self.config, 'XIGLRR', 'NOMATCHEN'):
                    lane = getbyname(self.config, 'XIGLRR', 'LANENTM')
                    Newsim.Log(self, 'INFO', "XIB for %s using LANENTM for packet %s" % (xigport.name, pts), pts)
                # step 5c
                else:
                    reginfo = [
                        "NTILEMEN = %x" % getbyname(self.config, 'XIGLRR', 'NTILEMEN'),
                        "STILEMEN = %x" % getbyname(self.config, 'XIGLRR', 'STILEMEN')
                    ]

                    Newsim.Log(self, 'CONFIG_ERROR', "XIB for %s got no ingress routing match for packet %s" % (xigport.name, pts), infolist=reginfo)


            with arbs[lane].request(priority=1) as req:
                # step 6a: wait for grant to trunk egress port
                yield req
                Newsim.Log(self, 'INFO', "TR ingress packet %s routed to %s on lane %d" % (pts, tegports[lane].name, lane), pts)
                # step 6b:
                yield self.env.process(tegports[lane].put(pts))
                # step 6c:
                yield xigport.get_tail()
