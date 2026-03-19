import SwiftUI

struct AssistantMessageExpandAction {
    let handler: (String) -> Void
}

private struct AssistantMessageExpandActionKey: EnvironmentKey {
    static let defaultValue: AssistantMessageExpandAction? = nil
}

extension EnvironmentValues {
    var assistantMessageExpandAction: AssistantMessageExpandAction? {
        get { self[AssistantMessageExpandActionKey.self] }
        set { self[AssistantMessageExpandActionKey.self] = newValue }
    }
}

struct ComposableMessageRow: View {
    let group: MessageRowGroup

    @State private var opacity: Double = 0
    @State private var blur: CGFloat = 10
    @State private var offset: CGFloat = 20

    private var message: Message {
        group.anchorMessage
    }

    private var rowVerticalPadding: CGFloat {
        if group.isStacked {
            return 4 + group.topSpacingAdjustment
        }
        if message.isAssistant || message.integrationBrand != nil {
            return 8 + group.topSpacingAdjustment
        }
        return 4 + group.topSpacingAdjustment
    }

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            if message.isUser {
                Spacer()
            }

            VStack(alignment: message.isUser ? .trailing : .leading, spacing: 4) {
                if group.isStacked {
                    MessageCardStack(group: group)
                } else {
                    messageCard(for: message, tiltDegrees: group.baseTiltDegrees)
                }
            }
            .onAppear {
                withAnimation(.easeOut(duration: 0.5)) {
                    opacity = 1.0
                    blur = 0
                    offset = 0
                }
            }

            if !message.isUser {
                Spacer()
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, rowVerticalPadding)
    }

    @ViewBuilder
    private func messageCard(for message: Message, tiltDegrees: Double) -> some View {
        let bubbleWidth = ConversationBubbleMetrics.width(for: message)

        if let integrationBrand = message.integrationBrand, message.isUser {
            IntegrationCommandCard(
                messageText: message.text,
                brand: integrationBrand,
                tiltDegrees: tiltDegrees,
                bubbleWidth: bubbleWidth
            )
        } else if message.isAssistant {
            AssistantResponseCard(
                messageText: message.text,
                tiltDegrees: tiltDegrees,
                bubbleWidth: bubbleWidth
            )
        } else {
            PlainTiltedMessageCard(
                messageText: message.text,
                tiltDegrees: tiltDegrees,
                bubbleWidth: bubbleWidth
            )
        }
    }
}

struct IntegrationCommandCard: View {
    let messageText: String
    let brand: MessageIntegrationBrand
    var tiltDegrees: Double = 3
    var bubbleWidth: CGFloat
    @SwiftUI.Environment(\.assistantMessageExpandAction) private var expandAction

    var body: some View {
        Card.commandPreview(
            iconName: brand.assetName,
            serviceName: brand.displayName,
            messageText: messageText,
            accentColor: brand.accentColor,
            gradient: brand.gradient,
            tiltDegrees: tiltDegrees
        )
        .frame(width: bubbleWidth, alignment: .trailing)
        .modifier(ExpandableMessageCardModifier(messageText: messageText, expandAction: expandAction))
    }
}

struct AssistantResponseCard: View {
    let messageText: String
    var tiltDegrees: Double = -3
    var bubbleWidth: CGFloat
    @SwiftUI.Environment(\.assistantMessageExpandAction) private var expandAction

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                MiloAppIcon()

                Text("Milo")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Color(red: 48 / 255, green: 206 / 255, blue: 236 / 255))

                Spacer(minLength: 0)
            }

            Text(messageText)
                .font(.system(size: 16, weight: .regular, design: .rounded))
                .foregroundStyle(.primary)
                .lineSpacing(2)
                .multilineTextAlignment(.leading)
                .lineLimit(Self.maximumCollapsedLineCount)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 16)
        .background(Color(uiColor: .secondarySystemBackground))
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .frame(width: bubbleWidth, alignment: .leading)
        .rotationEffect(.degrees(tiltDegrees))
        .shadow(color: Color.black.opacity(0.06), radius: 14, x: 0, y: 8)
        .modifier(ExpandableMessageCardModifier(messageText: messageText, expandAction: expandAction))
    }

    private static let maximumCollapsedLineCount = 4
}

struct MiloAppIcon: View {
    var body: some View {
        Image("MiloIcon")
            .resizable()
            .aspectRatio(contentMode: .fill)
            .frame(width: 26, height: 26)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.45), lineWidth: 0.75)
            )
    }
}

struct MessageRowGroup: Identifiable {
    let anchorMessage: Message
    let groupedMessages: [Message]
    let sourceIndex: Int
    let baseTiltDegrees: Double
    let topSpacingAdjustment: CGFloat

    var id: UUID {
        anchorMessage.id
    }

    var isStacked: Bool {
        groupedMessages.count > 1
    }

    var exposedTiltDegrees: Double {
        baseTiltDegrees
    }

    var preferredBubbleWidth: CGFloat {
        let visibleMessages = groupedMessages.filter(\.isDisplayable).suffix(3)
        return visibleMessages
            .map { ConversationBubbleMetrics.width(for: $0) }
            .max() ?? ConversationBubbleMetrics.maximumWidth
    }

    private var visibleStackCount: Int {
        max(groupedMessages.filter(\.isDisplayable).suffix(3).count, 1)
    }

    private var exposedStackIndex: Int {
        anchorMessage.isUser ? 0 : (visibleStackCount - 1)
    }

    func tiltDegrees(forStackIndex index: Int) -> Double {
        let distanceFromExposed = abs(index - exposedStackIndex)
        return distanceFromExposed.isMultiple(of: 2) ? baseTiltDegrees : -baseTiltDegrees
    }
}

private struct MessageCardStack: View {
    let group: MessageRowGroup

    private let verticalOverlap: CGFloat = 10

    private var stackedMessages: [Message] {
        Array(group.groupedMessages.filter(\.isDisplayable).suffix(3))
    }

    private var alignment: Alignment {
        group.anchorMessage.isUser ? .topTrailing : .topLeading
    }

    private var isUserStack: Bool {
        group.anchorMessage.isUser
    }

    var body: some View {
        Group {
            if stackedMessages.isEmpty {
                EmptyView()
            } else {
                ZStack(alignment: alignment) {
                    ForEach(Array(stackedMessages.enumerated()), id: \.element.id) { index, message in
                        cardView(for: message, at: index)
                            .offset(y: stackOffset(for: index))
                            .zIndex(Double(index))
                    }
                }
                .frame(
                    maxWidth: group.preferredBubbleWidth,
                    minHeight: 82 + (CGFloat(max(stackedMessages.count - 1, 0)) * verticalOverlap),
                    alignment: alignment
                )
            }
        }
    }

    @ViewBuilder
    private func cardView(for message: Message, at index: Int) -> some View {
        let tiltDegrees = group.tiltDegrees(forStackIndex: index)
        let bubbleWidth = group.preferredBubbleWidth

        if let integrationBrand = message.integrationBrand, message.isUser {
            IntegrationCommandCard(
                messageText: message.text,
                brand: integrationBrand,
                tiltDegrees: tiltDegrees,
                bubbleWidth: bubbleWidth
            )
        } else if message.isAssistant {
            AssistantResponseCard(
                messageText: message.text,
                tiltDegrees: tiltDegrees,
                bubbleWidth: bubbleWidth
            )
        } else {
            PlainTiltedMessageCard(
                messageText: message.text,
                tiltDegrees: tiltDegrees,
                bubbleWidth: bubbleWidth
            )
        }
    }

    private func stackOffset(for index: Int) -> CGFloat {
        if isUserStack {
            return CGFloat(stackedMessages.count - index - 1) * verticalOverlap
        }
        return CGFloat(index) * verticalOverlap
    }
}

struct PlainTiltedMessageCard: View {
    let messageText: String
    let tiltDegrees: Double
    let bubbleWidth: CGFloat
    @SwiftUI.Environment(\.assistantMessageExpandAction) private var expandAction

    var body: some View {
        Text(messageText)
            .font(.system(size: 16, weight: .regular, design: .rounded))
            .foregroundStyle(.primary)
            .lineSpacing(2)
            .multilineTextAlignment(.leading)
            .lineLimit(4)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 18)
            .padding(.vertical, 16)
            .background(Color(uiColor: .secondarySystemBackground))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .frame(width: bubbleWidth, alignment: .leading)
            .rotationEffect(.degrees(tiltDegrees))
            .shadow(color: Color.black.opacity(0.06), radius: 14, x: 0, y: 8)
            .modifier(ExpandableMessageCardModifier(messageText: messageText, expandAction: expandAction))
    }
}

private struct ExpandableMessageCardModifier: ViewModifier {
    let messageText: String
    let expandAction: AssistantMessageExpandAction?

    private var isExpandable: Bool {
        let normalized = messageText.replacingOccurrences(of: "\n", with: " ")
        return normalized.count > 110 || messageText.contains("\n")
    }

    func body(content: Content) -> some View {
        content
            .contentShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .onTapGesture {
                guard isExpandable else { return }
                expandAction?.handler(messageText)
            }
    }
}

struct ExpandedAssistantMessageOverlay: View {
    let text: String
    let onDismiss: () -> Void
    @State private var cardVisible = false

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .top) {
                Rectangle()
                    .fill(.ultraThinMaterial)
                    .opacity(cardVisible ? 1 : 0)
                    .ignoresSafeArea()
                    .onTapGesture(perform: onDismiss)

                VStack(alignment: .leading, spacing: 16) {
                    header

                    ScrollView {
                        Text(text)
                            .font(.system(size: 18, weight: .regular, design: .rounded))
                            .foregroundStyle(.primary)
                            .lineSpacing(4)
                            .multilineTextAlignment(.leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .scrollIndicators(.hidden)
                    .frame(maxHeight: min(geometry.size.height * 0.52, estimatedTextHeight))
                }
                .padding(20)
                .frame(maxWidth: 360, alignment: .leading)
                .background(Color(uiColor: .secondarySystemBackground).opacity(0.94))
                .overlay(
                    RoundedRectangle(cornerRadius: 28, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.08), lineWidth: 1)
                )
                .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
                .shadow(color: Color.black.opacity(0.22), radius: 24, x: 0, y: 14)
                .padding(.horizontal, 20)
                .padding(.top, 8)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .opacity(cardVisible ? 1 : 0)
                .offset(y: cardVisible ? 0 : 60)
            }
            .ignoresSafeArea(edges: .top)
            .onAppear {
                withAnimation(.easeOut(duration: 0.24)) {
                    cardVisible = true
                }
            }
            .onDisappear {
                cardVisible = false
            }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            HStack(spacing: 10) {
                MiloAppIcon()

                VStack(alignment: .leading, spacing: 2) {
                    Text("Milo")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(Color(red: 48 / 255, green: 206 / 255, blue: 236 / 255))

                    Text("Expanded response")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.secondary)
                }
            }

            Spacer(minLength: 0)

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(.primary)
                    .frame(width: 36, height: 36)
                    .background(Color(uiColor: .secondarySystemBackground).opacity(0.92))
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
        }
    }

    private var estimatedTextHeight: CGFloat {
        let bodyFont = UIFont.systemFont(ofSize: 18, weight: .regular)
        let constrainedWidth: CGFloat = 320
        let boundingRect = (text as NSString).boundingRect(
            with: CGSize(width: constrainedWidth, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: bodyFont],
            context: nil
        )
        return ceil(boundingRect.height) + 8
    }
}

struct OverlayPreviewTransitionModifier: ViewModifier {
    let opacity: Double
    let yOffset: CGFloat

    func body(content: Content) -> some View {
        content
            .opacity(opacity)
            .offset(y: yOffset)
    }
}

extension AnyTransition {
    static var overlayPreviewEntrance: AnyTransition {
        .modifier(
            active: OverlayPreviewTransitionModifier(opacity: 0, yOffset: 80),
            identity: OverlayPreviewTransitionModifier(opacity: 1, yOffset: 0)
        )
    }
}

extension MessageIntegrationBrand {
    var displayName: String {
        switch self {
        case .spotify: return "Spotify"
        case .gmail: return "Gmail"
        case .googleCalendar: return "Google Calendar"
        case .discord: return "Discord"
        case .todoist: return "Todoist"
        case .calendly: return "Calendly"
        case .uber: return "Uber"
        case .doordash: return "DoorDash"
        case .instacart: return "Instacart"
        case .appleMusic: return "Apple Music"
        }
    }

    var assetName: String {
        switch self {
        case .spotify: return "SpotifyIcon"
        case .gmail: return "GmailIcon"
        case .googleCalendar: return "GoogleCalendarIcon"
        case .discord: return "DiscordIcon"
        case .todoist: return "TodoistIcon"
        case .calendly: return "CalendlyIcon"
        case .uber: return "UberLogo"
        case .doordash: return "DoorDashIcon"
        case .instacart: return "InstacartIcon"
        case .appleMusic: return "AppleMusicIcon"
        }
    }

    var accentColor: Color {
        switch self {
        case .spotify: return Color(red: 0.12, green: 0.73, blue: 0.33)
        case .gmail: return Color(red: 0.86, green: 0.23, blue: 0.18)
        case .googleCalendar: return Color(red: 0.19, green: 0.46, blue: 0.95)
        case .discord: return Color(red: 0.35, green: 0.40, blue: 0.93)
        case .todoist: return Color(red: 0.88, green: 0.24, blue: 0.17)
        case .calendly: return Color(red: 0.05, green: 0.52, blue: 0.93)
        case .uber: return .black
        case .doordash: return Color(red: 0.92, green: 0.24, blue: 0.13)
        case .instacart: return Color(red: 0.29, green: 0.71, blue: 0.21)
        case .appleMusic: return Color(red: 0.96, green: 0.24, blue: 0.42)
        }
    }

    var gradient: LinearGradient {
        LinearGradient(
            colors: [Color.white, accentColor.opacity(0.08)],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}

enum ConversationBubbleMetrics {
    static let maximumWidth: CGFloat = 300
    private static let horizontalPadding: CGFloat = 36
    private static let minimumPlainWidth: CGFloat = 92
    private static let minimumAssistantWidth: CGFloat = 182
    private static let minimumIntegrationWidth: CGFloat = 196
    private static let maximumMeasuredTextWidth: CGFloat = maximumWidth - horizontalPadding
    private static let messageFont = UIFont.systemFont(ofSize: 16, weight: .regular)
    private static let serviceFont = UIFont.systemFont(ofSize: 15, weight: .semibold)
    private static let bodyLineHeight: CGFloat = UIFont.systemFont(ofSize: 16, weight: .regular).lineHeight + 2
    private static let preferredCollapsedLineCount: CGFloat = 3.2
    private static let maximumCollapsedLineCount: CGFloat = 4

    static func width(for message: Message) -> CGFloat {
        if let integrationBrand = message.integrationBrand, message.isUser {
            return integrationWidth(serviceName: integrationBrand.displayName, messageText: message.text)
        }
        if message.isAssistant {
            return assistantWidth(messageText: message.text)
        }
        return plainMessageWidth(messageText: message.text)
    }

    static func plainMessageWidth(messageText: String) -> CGFloat {
        let measuredWidth = wrappedTextWidth(
            for: messageText,
            font: messageFont,
            minimumWidth: minimumPlainWidth - horizontalPadding
        )
        return clamp(measuredWidth + horizontalPadding, minimum: minimumPlainWidth)
    }

    static func assistantWidth(messageText: String) -> CGFloat {
        let headerWidth = CGFloat(26 + 10) + textWidth(for: "Milo", font: serviceFont)
        let bodyWidth = wrappedTextWidth(
            for: messageText,
            font: messageFont,
            minimumWidth: minimumAssistantWidth - horizontalPadding
        )
        return clamp(max(headerWidth, bodyWidth) + horizontalPadding, minimum: minimumAssistantWidth)
    }

    static func integrationWidth(serviceName: String, messageText: String) -> CGFloat {
        let headerWidth = CGFloat(26 + 14) + textWidth(for: serviceName, font: serviceFont)
        let bodyWidth = wrappedTextWidth(
            for: messageText,
            font: messageFont,
            minimumWidth: minimumIntegrationWidth - horizontalPadding
        )
        return clamp(max(headerWidth, bodyWidth) + horizontalPadding, minimum: minimumIntegrationWidth)
    }

    private static func textWidth(for text: String, font: UIFont) -> CGFloat {
        let normalized = text
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return 0 }
        let measured = (normalized as NSString).size(withAttributes: [.font: font]).width
        return min(maximumMeasuredTextWidth, ceil(measured))
    }

    private static func wrappedTextWidth(for text: String, font: UIFont, minimumWidth: CGFloat) -> CGFloat {
        let normalized = text
            .replacingOccurrences(of: "\u{00A0}", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return minimumWidth }

        let singleLineWidth = textWidth(for: normalized, font: font)
        if singleLineWidth <= maximumMeasuredTextWidth {
            return max(minimumWidth, singleLineWidth)
        }

        let floorWidth = max(minimumWidth, longestTokenWidth(for: normalized, font: font))
        let targetHeight = bodyLineHeight * preferredCollapsedLineCount
        let fallbackHeight = bodyLineHeight * maximumCollapsedLineCount

        var bestWidth = maximumMeasuredTextWidth
        var bestHeight = CGFloat.greatestFiniteMagnitude
        var candidateWidth = floorWidth

        while candidateWidth <= maximumMeasuredTextWidth {
            let measuredHeight = textHeight(for: normalized, font: font, constrainedTo: candidateWidth)

            if measuredHeight <= targetHeight {
                return ceil(candidateWidth)
            }

            if measuredHeight < bestHeight {
                bestHeight = measuredHeight
                bestWidth = candidateWidth
            }

            candidateWidth += 12
        }

        if bestHeight <= fallbackHeight {
            return ceil(bestWidth)
        }

        return maximumMeasuredTextWidth
    }

    private static func textHeight(for text: String, font: UIFont, constrainedTo width: CGFloat) -> CGFloat {
        let measured = (text as NSString).boundingRect(
            with: CGSize(width: width, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: font],
            context: nil
        )
        return ceil(measured.height)
    }

    private static func longestTokenWidth(for text: String, font: UIFont) -> CGFloat {
        text
            .split(whereSeparator: \.isWhitespace)
            .map { token in
                ceil((String(token) as NSString).size(withAttributes: [.font: font]).width)
            }
            .max() ?? 0
    }

    private static func clamp(_ width: CGFloat, minimum: CGFloat) -> CGFloat {
        min(maximumWidth, max(minimum, width))
    }
}
