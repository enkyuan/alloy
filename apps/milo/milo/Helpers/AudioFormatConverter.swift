import Foundation
import AVFoundation

struct AudioFormatConverter {
    static func pcmBufferToRawPCM(buffer: AVAudioPCMBuffer) -> Data {
        switch buffer.format.commonFormat {
        case .pcmFormatFloat32:
            guard let channelData = buffer.floatChannelData else {
                return Data()
            }
            return convertFloat32ToInt16(buffer: buffer, channelData: channelData)
        case .pcmFormatInt16:
            guard let channelData = buffer.int16ChannelData else {
                return Data()
            }
            return convertInt16ToMono(buffer: buffer, channelData: channelData)
        case .pcmFormatInt32:
            guard let channelData = buffer.int32ChannelData else {
                return Data()
            }
            return convertInt32ToInt16(buffer: buffer, channelData: channelData)
        default:
            return Data()
        }
    }

    private static func convertFloat32ToInt16(
        buffer: AVAudioPCMBuffer,
        channelData: UnsafePointer<UnsafeMutablePointer<Float>>
    ) -> Data {
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)
        var int16Samples: [Int16] = []
        int16Samples.reserveCapacity(frameCount)

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

    private static func convertInt16ToMono(
        buffer: AVAudioPCMBuffer,
        channelData: UnsafePointer<UnsafeMutablePointer<Int16>>
    ) -> Data {
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)
        var monoSamples: [Int16] = []
        monoSamples.reserveCapacity(frameCount)

        if channelCount == 1 {
            monoSamples.append(contentsOf: UnsafeBufferPointer(start: channelData[0], count: frameCount))
            return Data(bytes: monoSamples, count: monoSamples.count * MemoryLayout<Int16>.size)
        }

        for frame in 0..<frameCount {
            var sum: Int32 = 0
            for channel in 0..<channelCount {
                sum += Int32(channelData[channel][frame])
            }
            let average = Int16(sum / Int32(channelCount))
            monoSamples.append(average)
        }

        return Data(bytes: monoSamples, count: monoSamples.count * MemoryLayout<Int16>.size)
    }

    private static func convertInt32ToInt16(
        buffer: AVAudioPCMBuffer,
        channelData: UnsafePointer<UnsafeMutablePointer<Int32>>
    ) -> Data {
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)
        var int16Samples: [Int16] = []
        int16Samples.reserveCapacity(frameCount)

        for frame in 0..<frameCount {
            var sum: Double = 0
            for channel in 0..<channelCount {
                sum += Double(channelData[channel][frame]) / Double(Int32.max)
            }
            let averagedSample = sum / Double(channelCount)
            let clampedSample = max(-1.0, min(1.0, averagedSample))
            let int16Sample = Int16(clampedSample * 32767.0)
            int16Samples.append(int16Sample)
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
