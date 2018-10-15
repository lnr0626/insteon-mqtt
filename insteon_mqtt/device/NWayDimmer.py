# ===========================================================================
#
# Pseudo N-Way Dimmer device module.  Used to combine multiple devices that
# act like a dimmer (including wall switches, lamp modules, and some remotes)
# into a single pseudo dimmer, or n-way dimmer.
#
# ===========================================================================
from .Base import Base
from .Dimmer import Dimmer
from .. import log
from .. import util
from ..CommandSeq import CommandSeq
from ..Signal import Signal

LOG = log.get_logger()


class NWayDimmer(Base):
    """Insteon n-way dimmer device.

    This aggregates multiple insteon dimmer devices (See Dimmer for more
    information).

    The Signal Dimmer.signal_level_changed will be emitted whenever
    the device level is changed with the calling sequence (device,
    level) where level is 0->0xff.

    When the states of secondary devices don't match the primary
    during a refresh, they will be overwritten with the value from
    the primary; however, updates from all devices will propagate
    to all the other devices.

    This currently requires all devices to be of the same type (i.e.
    a dimmer like device).

    Sample configuration input:

        insteon:
          devices:
            - n-way-dimmer:
              name: "Stair Lights"
              primary: 44.a3.79
              secondaries:
                - aa.bb.cc

    The run_command() method is used for arbitrary remote commanding
    (via MQTT for example).  The input is a dict (or keyword args)
    containing a 'cmd' key with the value as the command name and any
    additional arguments needed for the command as other key/value
    pairs. Valid commands for all devices are:

       getdb:    No arguments.  Download the PLM modem all link database
                 and save it to file.
       refresh:  No arguments.  Ping the device to get the current state and
                 see if the database is current.  Reloads the modem database
                 if needed.  This will emit the current state as a signal.
       on:       No arguments.  Turn the device on.
       off:      No arguments.  Turn the device off
       set:      Argument 'level' = 0->255 to set brightness level.  Optional
                 arg 'instant' with value True or False to change state
                 instantly (default=False).
       up:       No arguments.  Increment the current dimmer level up.
       down:     No arguments.  Increment the current dimmer level down.

    These commands will be propagated to all devices. The primary device
    is used to de-conflict state.
    """

    def __init__(self, protocol, modem, primary, secondaries=None, name=None):
        """Constructor

        Args:
          protocol:    (Protocol) The Protocol object used to communicate
                       with the Insteon network.  This is needed to allow
                       the device to send messages to the PLM modem.
          modem:       (Modem) The Insteon modem used to find other devices.
          primary:     (Address) The address of the device.
          name         (str) Nice alias name to use for the device.
        """
        # Important note here is that this 'device' is a psuedo device, and
        # so doesn't actually have an address. I'm not sure how that best
        # fits into things
        super().__init__(protocol, modem, primary, name)

        # Current dimming level. 0x00 -> 0xff
        self._level = 0x00

        self._primary = primary

        if secondaries is None:  # Don't provide a mutable default argument
            secondaries = []

        self._devices = {
            secondaries[i]: Dimmer(
                protocol,
                modem,
                secondaries[i],
                None if name is None else "%s-secondary-%d".format(name, i)
            ) for i in range(0, len(secondaries))  # indexed for-comprehension
            # to give each secondary a unique name
        }

        self._devices[self._primary] = Dimmer(
            protocol,
            modem,
            primary,
            None if name is None else "%s-primary".format(name)
        )

        # Support dimmer style signals and motion on/off style signals.
        self.signal_level_changed = Signal()  # (Device, level)

    # -----------------------------------------------------------------------
    def pair(self, on_done=None):
        """Pair the device with the modem.

        This only needs to be called one time.  It will set the device
        as a controller and the modem as a responder so the modem will
        see group broadcasts and report them to us.

        The device must already be a responder to the modem (push set
        on the modem, then set on the device) so we can update it's
        database.
        """
        LOG.error("Device %s doesn't support pairing yet", self.label)
        # LOG.info("Dimmer %s pairing", self.addr)
        #
        # # Build a sequence of calls to the do the pairing.  This insures each
        # # call finishes and works before calling the next one.  We have to do
        # # this for device db manipulation because we need to know the memory
        # # layout on the device before making changes.
        # seq = CommandSeq(self.protocol, "Dimmer paired", on_done)
        #
        # # Start with a refresh command - since we're changing the db, it must
        # # be up to date or bad things will happen.
        # seq.add(self.refresh)
        #
        # # Add the device as a responder to the modem on group 1.  This is
        # # probably already there - and maybe needs to be there before we can
        # # even issue any commands but this check insures that the link is
        # # present on the device and the modem.
        # seq.add(self.db_add_resp_of, 0x01, self.modem.addr, 0x01,
        #         refresh=False)
        #
        # # Now add the device as the controller of the modem for group 1.
        # # This lets the modem receive updates about the button presses and
        # # state changes.
        # seq.add(self.db_add_ctrl_of, 0x01, self.modem.addr, 0x01,
        #         refresh=False)
        #
        # # For scene simulation, the modem
        #
        # # Finally start the sequence running.  This will return so the
        # # network event loop can process everything and the on_done callbacks
        # # will chain everything together.
        # seq.run()

    # -----------------------------------------------------------------------
    def on(self, group=0x01, level=0xff, instant=False, on_done=None):
        """Turn the device on.

        This will send the command to the device to update it's state.
        When we get an ACK of the result, we'll change our internal
        state and emit the state changed signals.

        Args:
          level:    (int) If non zero, turn the device on.  Should be
                    in the range 0x00 to 0xff.
          instant:  (bool) False for a normal ramping change, True for an
                    instant change.
        """
        LOG.info("Dimmer %s cmd: on %s", self.addr, level)
        assert level >= 0 and level <= 0xff
        assert group == 0x01

        seq = CommandSeq(self.protocol, "Sub devices set to on", on_done)

        for addr, device in self._devices:
            seq.add(device.on, group, level, instant)

        seq.run()

    # -----------------------------------------------------------------------
    def off(self, group=0x01, instant=False, on_done=None):
        """Turn the device off.

        This will send the command to the device to update it's state.
        When we get an ACK of the result, we'll change our internal
        state and emit the state changed signals.

        Args:
          instant:  (bool) False for a normal ramping change, True for an
                    instant change.
        """
        LOG.info("Dimmer %s cmd: off", self.addr)
        assert group == 0x01

        seq = CommandSeq(self.protocol, "Sub devices set to off", on_done)

        for addr, device in self._devices:
            seq.add(device.off, group, instant)

        seq.run()

    # -----------------------------------------------------------------------
    def set(self, level, group=0x01, instant=False, on_done=None):
        """Set the device on or off.

        This will send the command to the device to update it's state.
        When we get an ACK of the result, we'll change our internal
        state and emit the state changed signals.

        Args:
          level:    (int/bool) If non zero, turn the device on.  Should be
                    in the range 0x00 to 0xff.  If True, the level will be
                    0xff.
          instant:  (bool) False for a normal ramping change, True for an
                    instant change.
        """
        if level:
            if level is True:
                level = 0xff

            self.on(group, level, instant, on_done)
        else:
            self.off(group, instant, on_done)

    # -----------------------------------------------------------------------
    def scene(self, is_on, group=0x01, on_done=None):
        """TODO: doc
        """
        LOG.info("Dimmer %s scene %s", self.addr, "on" if is_on else "off")
        assert group == 0x01

        seq = CommandSeq(self.protocol, "Sub devices scenes", on_done)

        for addr, device in self._devices:
            seq.add(device.scene, is_on, group)

        seq.run()

    # -----------------------------------------------------------------------
    def increment_up(self, on_done=None):
        """Increment the current level up.

        Levels increment in units of 8 (32 divisions from off to on).

        This will send the command to the device to update it's state.
        When we get an ACK of the result, we'll change our internal
        state and emit the state changed signals.
        """
        LOG.info("Dimmer %s cmd: increment up", self.addr)

        seq = CommandSeq(self.protocol, "Sub devices incremented up", on_done)

        for addr, device in self._devices:
            seq.add(device.increment_up)

        seq.run()

    # -----------------------------------------------------------------------
    def increment_down(self, on_done=None):
        """Increment the current level down.

        Levels increment in units of 8 (32 divisions from off to on).

        This will send the command to the device to update it's state.
        When we get an ACK of the result, we'll change our internal
        state and emit the state changed signals.
        """
        LOG.info("Dimmer %s cmd: increment down", self.addr)

        seq = CommandSeq(self.protocol, "Sub devices increment down", on_done)

        for addr, device in self._devices:
            seq.add(device.increment_down)

        seq.run()

    # -----------------------------------------------------------------------
    def set_backlight(self, level, on_done=None):
        """TODO: doc

        NOTE: default factory backlight == 0x1f
        """
        LOG.info("Dimmer %s setting backlight to %s", self.label, level)

        seq = CommandSeq(self.protocol, "Sub devices set backlight", on_done)

        for addr, device in self._devices:
            seq.add(device.set_backlight, level)

        seq.run()

    # -----------------------------------------------------------------------
    def set_on_level(self, level, on_done=None):
        """TODO: doc

        NOTE: default factory backlight == 0x1f
        """
        LOG.info("Dimmer %s setting on level to %s", self.label, level)

        seq = CommandSeq(self.protocol, "Sub devices set on level", on_done)

        for addr, device in self._devices:
            seq.add(device.set_on_level, level)

        seq.run()

    # -----------------------------------------------------------------------
    def set_flags(self, on_done, **kwargs):
        """TODO: doc
        valid kwargs:
           backlight: 0x11-0xff (factory default 0x1f)
        """
        LOG.info("Dimmer %s cmd: set flags", self.label)

        # Check the input flags to make sure only ones we can understand were
        # passed in.
        flags = set(["backlight", "on_level"])
        unknown = set(kwargs.keys()).difference(flags)
        if unknown:
            raise Exception("Unknown Dimmer flags input: %s.\n Valid flags "
                            "are: %s" % unknown, flags)

        seq = CommandSeq(self.protocol, "Dimmer set_flags complete", on_done)

        if "backlink" in kwargs:
            backlight = util.input_byte(kwargs, "backlight")
            seq.add(self.set_backlight, backlight)

        if "on_level" in kwargs:
            on_level = util.input_byte(kwargs, "on_level")
            seq.add(self.set_on_level, on_level)

        seq.run()
