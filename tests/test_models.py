"""Unit tests for models module."""

import pytest
from pc_app.models import ScheduledEvent, Block, PositionConfig, Profile, EVENTS


class TestScheduledEvent:
    """Tests for ScheduledEvent dataclass."""
    
    def test_create_scheduled_event(self):
        """Test creating a ScheduledEvent."""
        event = ScheduledEvent(event="Isolator On", start=0.0, duration=100.0)
        assert event.event == "Isolator On"
        assert event.start == 0.0
        assert event.duration == 100.0
    
    def test_scheduled_event_valid_types(self):
        """Test that all EVENTS are valid event types."""
        for event_type in EVENTS:
            event = ScheduledEvent(event=event_type, start=0.0, duration=10.0)
            assert event.event in EVENTS


class TestBlock:
    """Tests for Block dataclass."""
    
    def test_create_block(self):
        """Test creating a Block."""
        events = [
            ScheduledEvent("Isolator On", 0.0, 100.0),
            ScheduledEvent("DUT Hold Time", 50.0, 50.0),
        ]
        block = Block(block_name="Test Block", scheduled_events=events, cycles=5)
        assert block.block_name == "Test Block"
        assert len(block.scheduled_events) == 2
        assert block.cycles == 5
    
    def test_empty_block(self):
        """Test creating a block with no events."""
        block = Block(block_name="Empty", scheduled_events=[], cycles=1)
        assert len(block.scheduled_events) == 0
        assert block.cycles == 1


class TestPositionConfig:
    """Tests for PositionConfig dataclass."""
    
    def test_create_position_config(self):
        """Test creating a PositionConfig."""
        pos = PositionConfig(
            position=1,
            enabled=True,
            isolator_gpio=1,
            dut_gpio=21,
            dut_offset_ms=0.0
        )
        assert pos.position == 1
        assert pos.enabled is True
        assert pos.isolator_gpio == 1
        assert pos.dut_gpio == 21
        assert pos.dut_offset_ms == 0.0
    
    def test_disabled_position(self):
        """Test creating a disabled position."""
        pos = PositionConfig(
            position=2,
            enabled=False,
            isolator_gpio=2,
            dut_gpio=22,
            dut_offset_ms=5.0
        )
        assert pos.enabled is False


class TestProfile:
    """Tests for Profile dataclass."""
    
    def test_create_profile(self):
        """Test creating a complete Profile."""
        events = [ScheduledEvent("Isolator On", 0.0, 100.0)]
        blocks = [Block("Block 1", events, 1)]
        positions = [PositionConfig(1, True, 1, 21, 0.0)]
        
        profile = Profile(
            profile_name="Test Profile",
            waveform_time_units="ms",
            blocks=blocks,
            isolator_waveform_points=[(0.0, 0), (100.0, 1)],
            dut_waveform_points=[(50.0, 0), (150.0, 1)],
            row_delay_ms=0.0,
            positions=positions
        )
        
        assert profile.profile_name == "Test Profile"
        assert profile.waveform_time_units == "ms"
        assert len(profile.blocks) == 1
        assert len(profile.positions) == 1
        assert profile.row_delay_ms == 0.0
    
    def test_profile_with_multiple_blocks(self):
        """Test profile with multiple blocks."""
        block1 = Block("Init", [ScheduledEvent("Isolator On", 0, 100)], 1)
        block2 = Block("Main", [ScheduledEvent("DUT On Time", 0, 200)], 10)
        block3 = Block("Shutdown", [ScheduledEvent("Isolator Off", 0, 50)], 1)
        
        positions = [PositionConfig(1, True, 1, 21, 0.0)]
        
        profile = Profile(
            profile_name="Multi-Block",
            waveform_time_units="ms",
            blocks=[block1, block2, block3],
            isolator_waveform_points=[],
            dut_waveform_points=[],
            row_delay_ms=0.0,
            positions=positions
        )
        
        assert len(profile.blocks) == 3
        total_cycles = sum(b.cycles for b in profile.blocks)
        assert total_cycles == 12
