import simpy
from typing import (ContextManager,
    Generic,
    Optional,
    Type,
    NewType,
    Any,
    TypeVar,
    ClassVar,
    MutableSequence,

)
from types import TracebackType
from simpy.events import Process, Timeout, AnyOf
from simpy.resources import base
from simpy.core import BoundClass, Environment, Event
import time
from simpy.events import PENDING, EventPriority, URGENT, NORMAL

ResourceType = TypeVar('ResourceType', bound='BaseResource')

class NewEvent(Event):
    """An extension class of the native Simpy Event class.
    The only addition is that the succeed member method can defer the success 
    of the event to occur at some point in time. 

    """
    def __init__(self, env: 'Environment',item=None,caller=None):
        super().__init__(env)
        self.item=item
        self.caller=caller

    def succeed(self, value: Optional[Any] = None,delay=0) -> 'Event':
        """Set the event's value, mark it as successful and schedule it for
        processing at an arbitrary time in the future or now by the environment. 

        Returns the event instance.

        Raises :exc:`RuntimeError` if this event has already been triggerd.

        """
        if self._value is not PENDING:
            raise RuntimeError(f'{self} has already been triggered')

        self._ok = True
        self._value = value
        self.env.schedule(self,delay=delay)
        return self

class ConcurrentAllOf(NewEvent):
    """
        An event that is successful when a list of events provided as an argument are concurrently successful.
        This assumes that any of the event can revert from being successful to pending and hence all events in the
        list are checked each time to make sure all of them are successful AT THE SAME TIME before declaring
        the event successful.
        Whenever at least one of the events is not triggered, a callback to the check function is appended to its callbacks
        and the check function returns without declaring the event successful.
        
        Note that the list of events i a list of pointers to objects in the memory. These can change.
        Accordingly, an event may be triggered upon a first check, but a external function may restart
        replace that event with a new not-triggered event. When a second check happens, that event may be not triggered 
        and hence prevent the AllOf event from being successful.

    """
    def __init__(self, env, eventList):
        super().__init__(env)

        self.eventList=eventList
        self._check()

    def _check(self,event=None):

        for e in range(len(self.eventList)):

            if not self.eventList[e].triggered:
                
                self.eventList[e].callbacks.append(self._check)
                return

        self.succeed()

class BufferPeek(NewEvent):
    """Generic event for requesting to peek at something from the buffer.

    """

    def __init__(self, resource: ResourceType,item=None,caller=None):
        super().__init__(resource._env,item=item, caller=caller)
        self.resource = resource
        self.proc = self.env.active_process

        resource.peek_queue.append(self)
        # self.callbacks.append(resource._trigger_put)
        resource._trigger_peek()

    def __enter__(self) -> 'Peek':
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        self.cancel()
        return None

    def cancel(self) -> None:
        """Cancel this get request.

        This method has to be called if the get request must be aborted, for
        example if a process needs to handle an exception like an
        :class:`~simpy.exceptions.Interrupt`.

        If the get request was created in a :keyword:`with` statement, this
        method is called automatically.

        """
        if not self.triggered:
            self.resource.peek_queue.remove(self)

class BufferGet(NewEvent):
    """Generic event for requesting to get something from the *resource*.

    This event (and all of its subclasses) can act as context manager and can
    be used with the :keyword:`with` statement to automatically cancel the
    request if an exception (like an :class:`simpy.exceptions.Interrupt` for
    example) occurs:

    .. code-block:: python

        with res.get() as request:
            item = yield request

    """

    def __init__(self, resource: ResourceType,item=None,caller=None):
        super().__init__(resource._env,item=item,caller=caller)
        self.resource = resource
        self.proc = self.env.active_process
        resource.get_queue.append(self)

        # self.callbacks.append(resource._trigger_put)
        resource._trigger_get(None)

    def __enter__(self) -> 'Get':
        return self


    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        self.cancel()
        return None

    def cancel(self) -> None:
        """Cancel this get request.

        This method has to be called if the get request must be aborted, for
        example if a process needs to handle an exception like an
        :class:`~simpy.exceptions.Interrupt`.

        If the get request was created in a :keyword:`with` statement, this
        method is called automatically.

        """
        if not self.triggered:
            self.resource.get_queue.remove(self)

class BufferPut(NewEvent):
    """Generic event for requesting to put something into the *resource*.

    This event (and all of its subclasses) can act as context manager and can
    be used with the :keyword:`with` statement to automatically cancel the
    request if an exception (like an :class:`simpy.exceptions.Interrupt` for
    example) occurs:

    .. code-block:: python

        with res.put(item) as request:
            yield request

    """

    def __init__(self, resource: ResourceType, item:Any,caller=None):
        super().__init__(resource._env,item,caller=caller)
        self.resource = resource
        self.proc: Optional[Process] = self.env.active_process
        resource.put_queue.append(self)

        resource._trigger_put(None)

    def __enter__(self) -> 'Put':
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        self.cancel()
        return None

    def cancel(self) -> None:
        """Cancel this put request.

        This method has to be called if the put request must be aborted, for
        example if a process needs to handle an exception like an
        :class:`~simpy.exceptions.Interrupt`.

        If the put request was created in a :keyword:`with` statement, this
        method is called automatically.

        """
        if not self.triggered:
            self.resource.put_queue.remove(self)

class PipelinePut(NewEvent):
    """Generic event for requesting to put something into the *resource*.

    This event (and all of its subclasses) can act as context manager and can
    be used with the :keyword:`with` statement to automatically cancel the
    request if an exception (like an :class:`simpy.exceptions.Interrupt` for
    example) occurs:

    .. code-block:: python

        with res.put(item) as request:
            yield request

    """

    def __init__(self, resource: ResourceType, item:Any,caller=None):
        super().__init__(resource.env,item, caller=caller)
        self.resource = resource
        self.proc: Optional[Process] = self.env.active_process
        resource.put_queue.append(self)
        self.callbacks.append(self.resource._putReady)
        resource._trigger_put()

    def __enter__(self) -> 'PipelinePut':
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        self.cancel()
        return None

    def cancel(self) -> None:
        """Cancel this put request.

        This method has to be called if the put request must be aborted, for
        example if a process needs to handle an exception like an
        :class:`~simpy.exceptions.Interrupt`.

        If the put request was created in a :keyword:`with` statement, this
        method is called automatically.

        """
        if not self.triggered:
            self.resource.put_queue.remove(self)

class CrossbarGet(NewEvent):
    """An Event to retrieve a single packet chosen from multiple upstream ports
    of an xbar. The port from which the packet is chosen : 
        * an arbitratePkts() method of the xbar
        * 
    """

    def __init__(self, xbar, outPort=0):

        super().__init__(xbar.env, item=outPort)

        self.xbar=xbar
        self.xbar.get_queues[outPort].append(self)
        self.xbar.Log('DEBUG','Get from outPort {} is Requested'.format(self.item))

        unMaskedInPorts=[inPort for inPort in range(self.xbar.inPorts) if (self.xbar.routes[inPort]==outPort and self.xbar.unMaskEvents[inPort].triggered)]

        if unMaskedInPorts:
            self.xbar._schedule_arbitration(self.xbar.unMaskEvents[unMaskedInPorts[0]])