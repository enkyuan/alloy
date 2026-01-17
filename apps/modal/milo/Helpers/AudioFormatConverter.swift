import Foundation
import AVFoundation

struct AudioFormatConverter {
    static func pcmBufferToRawPCM(buffer: AVAudioPCMBuffer) -> Data {
        guard let channelData = buffer.floatChannelData else {
            return Data()
        }

        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)

        var int16Samples: [Int16] = []

        if channelCount == 1 {
            for frame in 0..<frameCount {
                let sample = channelData[0][frame]
                let clampedSample = max(-1.0, min(1.0, sample))
                let int16Sample = Int16(clampedSample * 32767.0)
                int16Samples.append(int16Sample)
            }
        } else {
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

        return Data(bytes: int16Samples, count: int16Samples.count * MemoryLayout<Int16>.size)
    }

    static func pcmBufferToWAV(buffer: AVAudioPCMBuffer, sampleRate: Double = 48000) -> Data {
        guard let channelData = buffer.floatChannelData else {
            return Data()
        }

        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)

        var int16Samples: [Int16] = []
        for frame in 0..<frameCount {
            for channel in 0..<channelCount {
                let sample = channelData[channel][frame]
                let clampedSample = max(-1.0, min(1.0, sample))
                let int16Sample = Int16(clampedSample * 32767.0)
                int16Samples.append(int16Sample)
            }
        }

        let pcmData = Data(bytes: int16Samples, count: int16Samples.count * MemoryLayout<Int16>.size)

        let wavHeader = createWAVHeader(
            dataSize: pcmData.count,
            sampleRate: Int(sampleRate),
            channelCount: channelCount
        )

        var wavData = Data()
        wavData.append(wavHeader)
        wavData.append(pcmData)

        return wavData
    }

    private static func createWAVHeader(dataSize: Int, sampleRate: Int, channelCount: Int) -> Data {
        var header = Data()

        let bitsPerSample = 16
        let byteRate = sampleRate * channelCount * bitsPerSample / 8
        let blockAlign = channelCount * bitsPerSample / 8
        let fileSize = 36 + dataSize

        header.append("RIFF".data(using: .ascii)!)
        header.append(UInt32(fileSize).littleEndianData)
        header.append("WAVE".data(using: .ascii)!)

        header.append("fmt ".data(using: .ascii)!)
        header.append(UInt32(16).littleEndianData)
        header.append(UInt16(1).littleEndianData)
        header.append(UInt16(channelCount).littleEndianData)
        header.append(UInt32(sampleRate).littleEndianData)
        header.append(UInt32(byteRate).littleEndianData)
        header.append(UInt16(blockAlign).littleEndianData)
        header.append(UInt16(bitsPerSample).littleEndianData)

        header.append("data".data(using: .ascii)!)
        header.append(UInt32(dataSize).littleEndianData)

        return header
    }
}

extension FixedWidthInteger {
    var littleEndianData: Data {
        var value = self.littleEndian
        return Data(bytes: &value, count: MemoryLayout<Self>.size)
    }
}
