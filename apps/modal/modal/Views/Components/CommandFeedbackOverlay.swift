//
//  CommandFeedbackOverlay.swift
//  modal
//
//  Temporary overlay showing command execution feedback
//

import SwiftUI

/// Overlay displaying command execution status and results
struct CommandFeedbackOverlay: View {
    let message: String?
    let isExecuting: Bool
    @State private var opacity: Double = 0
    @State private var scale: CGFloat = 0.9
    
    var body: some View {
        if let message = message {
            VStack(spacing: 12) {
                if isExecuting {
                    // Processing indicator
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .blue))
                        .scaleEffect(1.2)
                }
                
                Text(message)
                    .font(.system(size: 15, weight: .medium))
                    .foregroundColor(.primary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 20)
            }
            .padding(.vertical, 16)
            .padding(.horizontal, 24)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(.ultraThinMaterial)
                    .shadow(color: .black.opacity(0.1), radius: 10, x: 0, y: 5)
            )
            .opacity(opacity)
            .scaleEffect(scale)
            .onAppear {
                withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) {
                    opacity = 1.0
                    scale = 1.0
                }
            }
            .transition(.opacity.combined(with: .scale))
        }
    }
}

#Preview {
    VStack(spacing: 40) {
        CommandFeedbackOverlay(
            message: "Processing command...",
            isExecuting: true
        )
        
        CommandFeedbackOverlay(
            message: "Now playing 'Bohemian Rhapsody' by Queen",
            isExecuting: false
        )
        
        CommandFeedbackOverlay(
            message: nil,
            isExecuting: false
        )
    }
    .padding()
}
