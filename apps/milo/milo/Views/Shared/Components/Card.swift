import SwiftUI

struct Card: View {

    enum CardType {
        case servicePreview(ServicePreviewData)
        case integration(IntegrationData)
        case commandPreview(CommandPreviewData)
    }

<<<<<<<< HEAD:apps/modal/modal/Views/Shared/Components/Card.swift

========
>>>>>>>> codex/refactor:apps/milo/milo/Views/Shared/Components/Card.swift
    struct ServicePreviewData {
        let iconName: String
        let serviceName: String
        let shimmerText: String
        let albumCover: String?
    }

    struct IntegrationData {
        let iconName: String
        let serviceName: String
        let description: String
        let isConnected: Bool
        let action: () -> Void
    }

<<<<<<<< HEAD:apps/modal/modal/Views/Shared/Components/Card.swift

    let type: CardType


========
    struct CommandPreviewData {
        let iconName: String
        let serviceName: String
        let messageText: String
        let accentColor: Color
        let gradient: LinearGradient
        let tiltDegrees: Double
    }

    let type: CardType

>>>>>>>> codex/refactor:apps/milo/milo/Views/Shared/Components/Card.swift
    var body: some View {
        switch type {
        case .servicePreview(let data):
            servicePreviewCard(data)
        case .integration(let data):
            integrationCard(data)
        case .commandPreview(let data):
            commandPreviewCard(data)
        }
    }

<<<<<<<< HEAD:apps/modal/modal/Views/Shared/Components/Card.swift

========
>>>>>>>> codex/refactor:apps/milo/milo/Views/Shared/Components/Card.swift
    private func servicePreviewCard(_ data: ServicePreviewData) -> some View {
        Group {
            if let albumCover = data.albumCover {
                albumCardLayout(data: data, albumCover: albumCover)
            } else {
                standardCardLayout(data: data)
            }
        }
    }

    private func standardCardLayout(data: ServicePreviewData) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(data.iconName)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 20, height: 20)

                Text(data.serviceName)
                    .font(.system(size: 20, weight: .semibold))
            }

            AnimatedText(shimmer: data.shimmerText)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color(uiColor: .secondarySystemBackground))
        .cornerRadius(12)
    }

    private func albumCardLayout(data: ServicePreviewData, albumCover: String) -> some View {
        HStack(spacing: 16) {
            Image(albumCover)
                .resizable()
                .aspectRatio(contentMode: .fill)
                .frame(width: 60, height: 60)
                .cornerRadius(8)

            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 12) {
                    Image(data.iconName)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 20, height: 20)

                    Text(data.serviceName)
                        .font(.system(size: 20, weight: .semibold))
                }

                AnimatedText(shimmer: data.shimmerText)
            }

            Spacer()
        }
        .padding(16)
        .background(Color(uiColor: .secondarySystemBackground))
        .cornerRadius(12)
    }

<<<<<<<< HEAD:apps/modal/modal/Views/Shared/Components/Card.swift

    private func integrationCard(_ data: IntegrationData) -> some View {
        Button(action: data.action) {
            HStack(spacing: 16) {
                Image(data.iconName)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
========
    private func integrationCard(_ data: IntegrationData) -> some View {
        Button(action: data.action) {
            HStack(spacing: 16) {
                AdaptiveIcon(name: data.iconName)
>>>>>>>> codex/refactor:apps/milo/milo/Views/Shared/Components/Card.swift
                    .frame(width: 40, height: 40)

                VStack(alignment: .leading, spacing: 4) {
                    Text(data.serviceName)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundColor(.primary)

                    Text(data.description)
                        .font(.system(size: 14, weight: .regular))
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer()

                connectionIndicator(isConnected: data.isConnected)
            }
            .padding(16)
            .background(Color(uiColor: .secondarySystemBackground))
            .cornerRadius(12)
        }
        .buttonStyle(.plain)
    }

<<<<<<<< HEAD:apps/modal/modal/Views/Shared/Components/Card.swift
========
    private func commandPreviewCard(_ data: CommandPreviewData) -> some View {
        HStack(spacing: 14) {
            AdaptiveIcon(name: data.iconName)
                .frame(width: 26, height: 26)

            VStack(alignment: .leading, spacing: 8) {
                Text(data.serviceName)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(data.accentColor)
                    .frame(maxWidth: .infinity, alignment: .leading)

                highlightedCommandText(serviceName: data.serviceName, messageText: data.messageText)
                    .font(.system(size: 16, weight: .regular))
                    .foregroundStyle(.primary)
                    .lineSpacing(2)
                    .multilineTextAlignment(.leading)
                    .lineLimit(4)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .layoutPriority(1)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 16)
        .background(Color(uiColor: .secondarySystemBackground))
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .rotationEffect(.degrees(data.tiltDegrees))
        .shadow(color: Color.black.opacity(0.08), radius: 14, x: 0, y: 8)
    }

    private func highlightedCommandText(serviceName: String, messageText: String) -> Text {
        guard let range = messageText.range(of: serviceName, options: [.caseInsensitive]) else {
            return Text(messageText)
        }

        let prefix = String(messageText[..<range.lowerBound])
        let match = String(messageText[range])
        let suffix = String(messageText[range.upperBound...])

        return Text("\(Text(prefix))\(Text(match).bold())\(Text(suffix))")
    }

>>>>>>>> codex/refactor:apps/milo/milo/Views/Shared/Components/Card.swift
    private func connectionIndicator(isConnected: Bool) -> some View {
        Group {
            if isConnected {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 20))
                    .foregroundColor(.green)
            } else {
                Image(systemName: "chevron.right")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.secondary)
            }
        }
    }
}

<<<<<<<< HEAD:apps/modal/modal/Views/Shared/Components/Card.swift
========
// MARK: - AdaptiveIcon

private struct AdaptiveIcon: View {
    let name: String

    var body: some View {
        if name == "UberLogo" {
            UberLogoAdaptive()
        } else {
            Image(name)
                .resizable()
                .aspectRatio(contentMode: .fit)
        }
    }
}

struct UberLogoAdaptive: View {
    @SwiftUI.Environment(\.colorScheme) private var colorScheme: ColorScheme

    var body: some View {
        Image(colorScheme == .dark ? "UberLogoDark" : "UberLogoLight")
            .resizable()
            .aspectRatio(contentMode: .fit)
    }
}

// MARK: - Convenience Initializers
>>>>>>>> codex/refactor:apps/milo/milo/Views/Shared/Components/Card.swift

extension Card {
    static func servicePreview(
        iconName: String,
        serviceName: String,
        shimmerText: String,
        albumCover: String? = nil
    ) -> Card {
        Card(
            type: .servicePreview(
                ServicePreviewData(
                    iconName: iconName,
                    serviceName: serviceName,
                    shimmerText: shimmerText,
                    albumCover: albumCover
                )))
    }

    static func integration(
        iconName: String,
        serviceName: String,
        description: String,
        isConnected: Bool = false,
        action: @escaping () -> Void
    ) -> Card {
        Card(
            type: .integration(
                IntegrationData(
                    iconName: iconName,
                    serviceName: serviceName,
                    description: description,
                    isConnected: isConnected,
                    action: action
                )))
    }

    static func commandPreview(
        iconName: String,
        serviceName: String,
        messageText: String,
        accentColor: Color,
        gradient: LinearGradient,
        tiltDegrees: Double = 3
    ) -> Card {
        Card(
            type: .commandPreview(
                CommandPreviewData(
                    iconName: iconName,
                    serviceName: serviceName,
                    messageText: messageText,
                    accentColor: accentColor,
                    gradient: gradient,
                    tiltDegrees: tiltDegrees
                )))
    }
}
