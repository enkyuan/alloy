//
//  CommandModeIndicator.swift
//  modal
//
//  Visual indicator for command listening mode
//

import SwiftUI

/// Pulsing indicator shown when the assistant is in command mode
struct CommandModeIndicator: View {
    let isActive: Bool
    @State private var pulseScale: CGFloat = 1.0
    @State private var pulseOpacity: Double = 0.6
    
    var body: some View {
        if isActive {
            HStack(spacing: 8) {
                // Pulsing circle
                Circle()
                    .fill(Color.blue)
                    .frame(width: 12, height: 12)
                    .scaleEffect(pulseScale)
                    .opacity(pulseOpacity)
                    .onAppear {
                        withAnimation(
                            .easeInOut(duration: 1.0)
                            .repeatForever(autoreverses: true)
                        ) {
                            pulseScale = 1.3
                            pulseOpacity = 0.3
                        }
                    }
                
                Text("Listening for command...")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(.blue)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 20)
                    .fill(Color.blue.opacity(0.1))
            )
            .transition(.opacity.combined(with: .scale))
        }
    }
}

#Preview {
    VStack(spacing: 20) {
        CommandModeIndicator(isActive: true)
        CommandModeIndicator(isActive: false)
    }
    .padding()
}
