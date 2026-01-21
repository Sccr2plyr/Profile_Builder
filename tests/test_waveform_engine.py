"""Unit tests for waveform_engine module."""

import pytest
from pc_app.models import ScheduledEvent, Block
from pc_app.waveform_engine import (
    build_waveforms_from_schedule,
    build_waveforms_from_blocks,
    build_preview_channels
)


class TestBuildWaveformsFromSchedule:
    """Tests for single schedule waveform generation."""
    
    def test_simple_schedule(self):
        """Test generating waveforms from a simple schedule."""
        schedule = [
            ScheduledEvent("Isolator On", 0.0, 100.0),
            ScheduledEvent("DUT Hold Time", 50.0, 50.0),
        ]
        
        iso_dig, dut_dig, iso_disp, dut_disp, iso_ramps, dut_ramps, length = \
            build_waveforms_from_schedule(schedule, "ms", cycles=1)
        
        assert len(iso_dig) > 0
        assert len(dut_dig) > 0
        assert length > 0
        assert isinstance(iso_ramps, bool)
        assert isinstance(dut_ramps, bool)
    
    def test_multiple_cycles(self):
        """Test waveform generation with multiple cycles."""
        schedule = [ScheduledEvent("Isolator On", 0.0, 50.0)]
        
        iso_dig_1, _, _, _, _, _, length_1 = \
            build_waveforms_from_schedule(schedule, "ms", cycles=1)
        
        iso_dig_3, _, _, _, _, _, length_3 = \
            build_waveforms_from_schedule(schedule, "ms", cycles=3)
        
        # With 3 cycles, total length should be roughly 3x longer
        assert length_3 > length_1 * 2.5
    
    def test_empty_schedule(self):
        """Test that empty schedule raises error."""
        with pytest.raises(ValueError, match="At least one schedule block required"):
            build_waveforms_from_schedule([], "ms", cycles=1)
    
    def test_unit_conversion(self):
        """Test time unit conversion."""
        schedule = [ScheduledEvent("Isolator On", 0.0, 1.0)]
        
        # 1 ms vs 1 sec
        _, _, _, _, _, _, length_ms = build_waveforms_from_schedule(schedule, "ms", 1)
        _, _, _, _, _, _, length_sec = build_waveforms_from_schedule(schedule, "sec", 1)
        
        # 1 second should be 1000x longer than 1 millisecond
        assert abs(length_sec - length_ms * 1000) < 50  # Allow small tolerance


class TestBuildWaveformsFromBlocks:
    """Tests for multi-block waveform generation."""
    
    def test_single_block(self):
        """Test waveform generation with single block."""
        block = Block(
            block_name="Test",
            scheduled_events=[ScheduledEvent("Isolator On", 0.0, 100.0)],
            cycles=1
        )
        
        iso_dig, dut_dig, iso_disp, dut_disp, iso_ramps, dut_ramps, total_len, block_ends = \
            build_waveforms_from_blocks([block], "ms")
        
        assert len(iso_dig) > 0
        assert len(block_ends) == 1
        assert total_len > 0
    
    def test_multiple_blocks_sequential(self):
        """Test that multiple blocks execute sequentially."""
        block1 = Block("Block1", [ScheduledEvent("Isolator On", 0.0, 100.0)], 1)
        block2 = Block("Block2", [ScheduledEvent("DUT On Time", 0.0, 50.0)], 1)
        
        iso_dig, dut_dig, _, _, _, _, total_len, block_ends = \
            build_waveforms_from_blocks([block1, block2], "ms")
        
        # Should have 2 block end times
        assert len(block_ends) == 2
        
        # Second block should start after first block ends
        assert block_ends[0] < block_ends[1]
        
        # Total length should be sum of both blocks
        assert total_len == block_ends[-1]
    
    def test_blocks_with_different_cycles(self):
        """Test blocks with different cycle counts."""
        block1 = Block("Init", [ScheduledEvent("Isolator On", 0, 50)], cycles=1)
        block2 = Block("Main", [ScheduledEvent("DUT Hold Time", 0, 50)], cycles=5)
        
        _, _, _, _, _, _, total_len, block_ends = \
            build_waveforms_from_blocks([block1, block2], "ms")
        
        # Block 2 should end much later due to 5 cycles
        assert block_ends[1] > block_ends[0] * 4
    
    def test_empty_blocks_list(self):
        """Test that empty blocks list raises error."""
        with pytest.raises(ValueError):
            build_waveforms_from_blocks([], "ms")


class TestBuildPreviewChannels:
    """Tests for preview channel generation."""
    
    def test_preview_channels_creation(self):
        """Test creating preview channels."""
        from pc_app.models import PositionConfig
        
        positions = [
            PositionConfig(1, True, 1, 21, 0.0),
            PositionConfig(2, True, 2, 22, 0.0),
        ]
        
        iso_display = [(0.0, 0.0), (100.0, 1.0)]
        dut_display = [(50.0, 0.0), (150.0, 1.0)]
        iso_digital = [(0, 0), (100, 1)]
        dut_digital = [(50, 0), (150, 1)]
        
        channels = build_preview_channels(
            positions=positions,
            row_delay_ms=0.0,
            iso_display=iso_display,
            dut_display=dut_display,
            iso_digital=iso_digital,
            dut_digital=dut_digital
        )
        
        # Should have 4 channels (2 positions x 2 types)
        assert len(channels) == 4
        assert "ISO Pos-1 (GPIO 1)" in channels
        assert "DUT Pos-1 (GPIO 21)" in channels
