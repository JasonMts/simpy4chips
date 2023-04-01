
"""This module implements the core Component classes from which all active components are derived along
    with the helper tools to connect components and units"""

import logging

class ComponentBase(object):

    """Common class that all components and units inherits from. It collects common member vars and implements common logging
        
        Variables:
           * env (simpy.Environment): the simpy environment that the component/unit belongs to
           * name (string): the name of the component/unit
           * parent (object) : points to the parent component/unit if this is a sub-component, None if not
           * fullname (string): point separated hierarchy of the component (family tree)
           * action (simpy.Event): variable storing a reference to the action taken by the component
                when simulation starts
           * logger: instane of the logging.getLogger() to make is simple to add logs for debug
        
        Methods:
           * __init__() : initialize the component using environment,name and parent
           * run()      : the code that runs when simulation begins, customizable, by default it does nothing and is done
                        after 1 tick. This will be customized for the purpose of the system being simulated
           * Log()      : helper function that allows simple logging by setting message type and the message
           * setLogLevel(l): sets the log level existing in the python logging package to control how much info
                             the user wants in the log files (eg INFO, DEBUG, ERROR)
    """


    def __init__(self, env, name, parent=None):

        self.env = env
        self.name = name
        self.parent=parent
        self.fullname = (parent.fullname + "."  if parent!=None else "") + name
        self.action = self.env.process(self.run())
        self.logger = logging.getLogger(self.fullname)

    def run(self):

        """Dummy simpy run function for the base class; completes after one time simpy tick"""
        yield self.env.timeout(1)

    def Log(self, msgtype, msg, pkt=None, infolist=None):

        """Common logging function used by all components/units classes

        Arguments:
           msgtype(string) : One of 'FATAL_ERROR', 'WARNING', INFO', 'DEBUG'
           msg(string)     : The message to be logged, specified by the component
           pkt(ElPktHdr)   : Packet related messages may pass the packet concerned in order to enable
                             packet info message filtering
           infolist(list)  : Some messages may pass this list of strings as arbitrary additional debug
                             info to be logged"""

        # construct the output from the current sim time, objects full pathname and the passed message
        fullmsg = '[@%d]%s : %s' % (self.env.now, self.fullname, msg)
        displayinfo = True


        # always output the message if it is an error message or warning
        if msgtype == 'FATAL_ERROR':
            self.logger.error(fullmsg)
        elif msgtype == 'WARNING':
            self.logger.warning(fullmsg)
        elif msgtype == 'INFO':
            # info messages can be suppressed according to packet id
            if displayinfo:
                self.logger.info(fullmsg)
        elif msgtype == 'DEBUG':
            self.logger.debug(fullmsg)
        else:
            raise RuntimeError("ERROR: Unsupported message type [%s] in %s " % (msgtype, self.fullname))

        # some messages pass a list of strings which provides more debug info relating to the message
        # if this argument is present, print out the strings (unless message is being suppressed)
        if infolist and displayinfo:
            self.logger.info("\tInfodump follows:")
            for item in infolist:
                self.logger.info("\t%s" % item)

        # finally, if the message was an error, raise an exception.
        if 'ERRROR' in msgtype:
            raise RuntimeError(fullmsg)

    def setLogLevel(self,level):
        self.logger.setLevel(level)

class Component(ComponentBase):

    """A Generic class defining a smallest connectable entity. It inherits from the ComponentBase class.
        While it can connect to other components/units, it shall not contain any connectable sub-components.

        Variables:
            * toUp   : a dictionary of all the upstream entities that feed into the current component (becomes variable if single downstream)
            * fromUp : a dictionary of all the variables inside the current component that are connected to the upstream components in toUp
            * toDn   : a dictionary of all the downstream destinations of the current components (becomes variable if single downstream)
            * fromDn : a dictionary of all the variables inside the current components that are connected to the downstream

            """

    def __init__(self,env,name,parent=None):
    
        ComponentBase.__init__(self,env,name,parent)
        self.toUp={}
        self.toDn={}
        self.fromUp={}
        self.fromDn={}

class Unit(Component):

    """ Class for a generic unit that may contain multiple connected components and units. It provides 
        the methods necessary to connect the internal components and present the unit with a set of interfaces.
        it inherits from the Component class.

        Arguments:
            * unitDict : a dictionary of all the sub-components and sub-units that form the current unit
            * connList : a list of all the different connections between the different components

        Methods:
            * init(): initialize an empty component with the empty variables
            * addUnit(): adds a sub-unit (component) to unitDict
            * connect : main method for connecting the different sub-components and sub-units inside the main unit
                        as well as exposing the main unit interface to outside units (through the toUp, toDn, fromUp, fromDn dictionaries)
                        it takes as argument the source and destination units(components) as well as the src/dest ports (if any)
            * unitConns(): when there are sub-units inside the main unit, this is a recursive method for completing the connection
                            defined by the connect method
        """
    def __init__(self,env,name,parent=None):

        Component.__init__(self,env,name,parent)
        self.unitDict = {}
        self.connList = []
        if self.parent:
            self.parent.addUnit(self.name, self)

    def addUnit(self, name, unit):
        self.unitDict[name] = unit

    def connect(self, fromUnit, toUnit, fromPort=None, toPort=None):
        """Connection method for connecting between sub-units or sub-components or to connect sub-units or sub-compoents to the parent unit. 
        Requires a subsequent call to unitConns from the top-level unit or platform to complete all the requested connections

        Arguments:
           fromUnit(unit/component instance) : Source unit/componnet for the connection. If this is set to self, the connection is made from the parent's ports to the toUnit
           toUnit(unit/component instance)   : Destination unit/componnet for the connection. If this is set to self, the connection is made from the fromUnit to the parent's ports
           fromPort(dictKey)   : Key into the fromUnit's downstream port dictionaries, can be a string or int. Optional argument in the case that the fromUnit has only a single downstream port
           toPort(dictKey)     : Key into the toUnit's upstream port dictionaries, can be a string or int. Optional argument in the case that the toUnit has only a single upstream port"""

        # construct the output from the current sim time, objects full pathname and the passed message
        if toUnit is self:
            self.Log("DEBUG", "connect(): connecting fromUnit: %s to self: %s" % (fromUnit.fullname, self.fullname))
            if fromPort is not None and toPort is not None:
                self.fromDn[fromPort] = fromUnit.fromDn[toPort]
                self.connList.append([[self, 'toDn', toPort], [fromUnit, 'toDn', toPort]])
                self.Log("DEBUG", "  --  connecting               fromUnit: %s.fromDn to self: %s.fromDn, %s.fromDn[%s] is now %s" % (fromUnit.fullname, self.fullname, str(fromPort), self.fullname, self.fromDn[fromPort]))
                self.Log("DEBUG", "  --  scheduling connection of fromUnit: %s.toDn[%s] to self: %s.toDn[%s]" % (fromUnit.fullname, str(fromPort), self.fullname, str(toPort)))
            elif fromPort is not None:
                self.fromDn[fromPort] = fromUnit.fromDn
                self.connList.append([[self, 'toDn'],         [fromUnit, 'toDn', fromPort]])
                self.Log("DEBUG", "  --  connecting fromUnit: %s.fromDn to self: %s.fromDn, %s.fromDn[%s] is now %s" % (fromUnit.fullname, self.fullname, str(fromPort), self.fullname, self.fromDn[fromPort]))
                self.Log("DEBUG", "  --  scheduling connection of fromUnit: %s.toDn[%s] to self: %s.toDn" % (fromUnit.fullname, str(fromPort), self.fullname))
            elif toPort is not None:
                self.fromDn[toPort]=fromUnit.fromDn
                self.toDn[toPort]=None
                self.connList.append([[self, 'toDn', toPort], [fromUnit, 'toDn']])
                self.Log("DEBUG", "  --  connecting fromUnit: %s.fromDn to self: %s.fromDn, %s.fromDn is now %s" % (fromUnit, self.fullname, self.fullname, self.fromDn))
                self.Log("DEBUG", "  --  scheduling connection of fromUnit: %s.toDn to self: %s.toDn[%s]" % (fromUnit.fullname, self.fullname, str(toPort)))
            else:
                self.fromDn = fromUnit.fromDn
                self.connList.append([[self, 'toDn'],         [fromUnit, 'toDn']])
                self.Log("DEBUG", "  --  connecting fromUnit: %s.fromDn to self: %s.fromDn, %s.fromDn is now %s" % (fromUnit, self.fullname, self.fullname, self.fromDn))
                self.Log("DEBUG", "  --  scheduling connection of fromUnit: %s.toDn to self: %s.toDn" % (fromUnit.fullname, self.fullname))
        elif fromUnit is self:
            self.Log("DEBUG", "connect(): connecting self: %s to toUnit: %s" % (self.fullname, toUnit.fullname))
            if fromPort is not None and toPort is not None:
                self.fromUp[fromPort] = toUnit.fromUp[toPort]
                self.connList.append([[self, 'toUp', fromPort], [toUnit, 'toUp', toPort]])  
                self.Log("DEBUG", "  --  connecting               self: %s.fromUp[%s] to toUnit: %s.fromUp[%s], %s.fromUp[%s] is now %s" % (self.fullname, str(fromPort), toUnit.fullname, str(toPort), str(fromPort), self.fullname, self.fromUp[fromPort]))
                self.Log("DEBUG", "  --  scheduling connection of self: %s.toUp[%s] to toUnit: %s.toUp[%s]" % (self.fullname, str(fromPort), toUnit.fullname, str(toPort)))
            elif fromPort is not None:
                self.fromUp[fromPort] = toUnit.fromUp
                self.toUp[fromPort]=None
                self.connList.append([[self, 'toUp', fromPort], [toUnit, 'toUp']])
                self.Log("DEBUG", "  --  connecting               self: %s.fromUp[%s] to toUnit: %s.fromUp, %s.fromUp[%s] is now %s" % (self.fullname, str(fromPort), toUnit.fullname, str(fromPort), self.fullname, self.fromUp[fromPort]))
                self.Log("DEBUG", "  --  scheduling connection of self: %s.toUp[%s] to toUnit: %s.toUp" % (self.fullname, str(fromPort), toUnit.fullname))
            elif toPort is not None:
                self.fromUp = toUnit.fromUp[toPort]
                self.connList.append([[self, 'toUp'],           [toUnit, 'toUp', toPort]])
                self.Log("DEBUG", "  --  connecting               self: %s.fromUp to toUnit: %s.fromUp[%s], %s.fromUp is now %s" % (self.fullname, toUnit.fullname, str(toPort), self.fullname, self.fromUp))
                self.Log("DEBUG", "  --  scheduling connection of self: %s.toUp to toUnit: %s.toUp[%s]" % (self.fullname, toUnit.fullname, str(toPort)))
            else:
                self.fromUp = toUnit.fromUp
                self.connList.append([[self, 'toUp'],           [toUnit, 'toUp']])
                self.Log("DEBUG", "  --  connecting               self: %s.fromUp to toUnit: %s.fromUp, %s.fromUp is now %s" % (self.fullname, toUnit.fullname, self.fullname, self.fromUp))
                self.Log("DEBUG", "  --  scheduling connection of self: %s.toUp to toUnit: %s.toUp" % (self.fullname, toUnit.fullname))
        else:

            self.Log("DEBUG", "connect(): fromUnit: %s, toUnit: %s" % (fromUnit.fullname, toUnit.fullname))

            if fromPort is not None and toPort is not None:

                fromUnit.toDn[fromPort] = toUnit.fromUp[toPort]
                self.Log("DEBUG", "  --  connecting toUnit: %s.fromUp[%s] to fromUnit: %s.toDn[%s], %s.toDn[%s] is now %s" % (toUnit.fullname, str(toPort), fromUnit.fullname, str(fromPort), fromUnit.fullname, str(fromPort), fromUnit.toDn[fromPort].fullname))

            elif fromPort is not None:
                fromUnit.toDn[fromPort] = toUnit.fromUp
                self.Log("DEBUG", "  --  connecting toUnit: %s.fromUp to fromUnit: %s.toDn[%s], %s.toDn[%s] is now %s" % (toUnit.fullname, fromUnit.fullname, str(fromPort), fromUnit.fullname, str(fromPort), fromUnit.toDn[fromPort].fullname))

            elif toPort is not None:
                fromUnit.toDn           = toUnit.fromUp[toPort]
                self.Log("DEBUG", "  --  connecting toUnit: %s.fromUp[%s] to fromUnit: %s.toDn, %s.toDn is now %s" % (toUnit.fullname, str(toPort), fromUnit.fullname, fromUnit.fullname, fromUnit.toDn.fullname))

            else:
                fromUnit.toDn           = toUnit.fromUp
                self.Log("DEBUG", "  --  connecting toUnit: %s.fromUp to fromUnit: %s.toDn, %s.toDn is now %s" % (toUnit.fullname, fromUnit.fullname, fromUnit.fullname, fromUnit.toDn.fullname))

            # down->up connection

            if fromPort is not None and toPort is not None:
                toUnit.toUp[toPort] = fromUnit.fromDn[fromPort]
                self.Log("DEBUG", "  --  connecting fromUnit: %s.fromDn[%s] to toUnit: %s.toUp[%s], %s.toUp[%s] is now %s" % (fromUnit.fullname, str(fromPort), toUnit.fullname, str(toPort), toUnit.fullname, str(toPort), toUnit.toUp[toPort].fullname))

            elif fromPort is not None:
                toUnit.toUp         = fromUnit.fromDn[fromPort]
                self.Log("DEBUG", "  --  connecting fromUnit: %s.fromDn[%s] to toUnit: %s.toUp, %s.toUp is now %s" % (fromUnit.fullname, str(fromPort), toUnit.fullname, toUnit.fullname, toUnit.toUp.fullname))

            elif toPort is not None:
                toUnit.toUp[toPort] = fromUnit.fromDn
                self.Log("DEBUG", "  --  connecting fromUnit: %s.fromDn to toUnit: %s.toUp[%s], %s.toUp[%s] is now %s" % (fromUnit.fullname, toUnit.fullname, str(toPort), toUnit.fullname, str(toPort), toUnit.toUp[toPort].fullname))

            else:
                toUnit.toUp         = fromUnit.fromDn
                self.Log("DEBUG", "  --  connecting fromUnit: %s.fromDn to toUnit: %s.toUp, %s.toUp is now %s" % (fromUnit.fullname, toUnit.fullname, toUnit.fullname, toUnit.toUp.fullname))

    def unitConns(self):

        """Recursive method for completing all connections between units and components as defined by the calls to the connect() method 
        invoked in both the top level unit and all levles of hierarchy below.

        Arguments: None"""

        for unit in self.unitDict.values():
            for fromList,toList in unit.connList:
                if len(fromList) > 2:
                    fr = vars(fromList[0])[fromList[1]][fromList[2]]
                    frStr = fromList[0].fullname+'.'+fromList[1]+'['+str(fromList[2])+']'
                else:
                    fr = vars(fromList[0])[fromList[1]]
                    frStr = fromList[0].fullname+'.'+fromList[1]
                if len(toList) > 2:
                    vars(toList[0])[toList[1]][toList[2]] = fr
                    toStr = toList[0].fullname+'.'+toList[1]+'['+str(toList[2])+']'
                else:
                    vars(toList[0])[toList[1]] = fr
                    toStr = toList[0].fullname+'.'+toList[1]
                self.Log("DEBUG", "unitConns() connecting %s to %s" % (frStr, toStr))
            unit.unitConns()

