import Foundation
import AVFoundation

/// Utility for converting audio formats
struct AudioFormatConverter {
    /// Convert PCM buffer to raw PCM Int16 data (no WAV header)
    /// This is used for streaming to Soniox which expects raw PCM
    /// Automatically converts multi-channel audio to mono by averaging channels
    static func pcmBufferToRawPCM(buffer: AVAudioPCMBuffer) -> Data {
        guard let channelData = buffer.floatChannelData else {
            return Data()
        }
        
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)
        
        // Convert Float32 PCM to Int16 PCM
        var int16Samples: [Int16] = []
        
        if channelCount == 1 {
            // Mono audio - simple conversion
            for frame in 0..<frameCount {
                let sample = channelData[0][frame]
                let clampedSample = max(-1.0, min(1.0, sample))
                let int16Sample = Int16(clampedSample * 32767.0)
                int16Samples.append(int16Sample)
            }
        } else {
            // Multi-channel audio - mix down to mono by averaging all channels
            for frame in 0..<frameCount {
                var sum: Float = 0.0
                for channel in 0..<channelCount {
                    sum += channelData[channel][frame]
                }
                let averagedSample = sum / Float(channelCount)
                let clampedSample = max(-1.0, min(1.0, averagedSample))
                let int16Sample = Int16(clampedSample * 32767.0)
                int16Samples.append(int16Sample)
            }
        }
        
        // Return raw PCM data (no header)
        return Data(bytes: int16Samples, count: int16Samples.count * MemoryLayout<Int16>.size)
    }
    
    /// Convert PCM buffer to WAV format with proper headers
    static func pcmBufferToWAV(buffer: AVAudioPCMBuffer, sampleRate: Double = 48000) -> Data {
        guard let channelData = buffer.floatChannelData else {
            return Data()
        }
        
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)
        
        // Convert Float32 PCM to Int16 PCM
        var int16Samples: [Int16] = []
        for frame in 0..<frameCount {
            for channel in 0..<channelCount {
                let sample = channelData[channel][frame]
                // Clamp and convert to Int16
                let clampedSample = max(-1.0, min(1.0, sample))
                let int16Sample = Int16(clampedSample * 32767.0)
                int16Samples.append(int16Sample)
            }
        }
        
        // Create WAV data
        let pcmData = Data(bytes: int16Samples, count: int16Samples.count * MemoryLayout<Int16>.size)
        
        // Create WAV header
        let wavHeader = createWAVHeader(
            dataSize: pcmData.count,
            sampleRate: Int(sampleRate),
            channelCount: channelCount
        )
        
        // Combine header + PCM data
        var wavData = Data()
        wavData.append(wavHeader)
        wavData.append(pcmData)
        
        return wavData
    }
    
    /// Create WAV file header
    private static func createWAVHeader(dataSize: Int, sampleRate: Int, channelCount: Int) -> Data {
        var header = Data()
        
        let bitsPerSample = 16
        let byteRate = sampleRate * channelCount * bitsPerSample / 8
        let blockAlign = channelCount * bitsPerSample / 8
        let fileSize = 36 + dataSize
        
        // RIFF header
        header.append("RIFF".data(using: .ascii)!)
        header.append(UInt32(fileSize).littleEndianData)
        header.append("WAVE".data(using: .ascii)!)
        
        // fmt chunk
        header.append("fmt ".data(using: .ascii)!)
        header.append(UInt32(16).littleEndianData) // Subchunk1Size (16 for PCM)
        header.append(UInt16(1).littleEndianData)  // AudioFormat (1 = PCM)
        header.append(UInt16(channelCount).littleEndianData)
        header.append(UInt32(sampleRate).littleEndianData)
        header.append(UInt32(byteRate).littleEndianData)
        header.append(UInt16(blockAlign).littleEndianData)
        header.append(UInt16(bitsPerSample).littleEndianData)
        
        // data chunk
        header.append("data".data(using: .ascii)!)
        header.append(UInt32(dataSize).littleEndianData)
        
        return header
    }
}

// Helper extension for little-endian data
extension FixedWidthInteger {
    var littleEndianData: Data {
        var value = self.littleEndian
        return Data(bytes: &value, count: MemoryLayout<Self>.size)
    }
}
