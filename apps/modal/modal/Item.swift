//
//  Item.swift
//  modal
//
//  Created by Enkang Yuan on 10/12/25.
//

import Foundation

#if swift(>=5.9) && canImport(SwiftData)
import SwiftData

@Model
final class Item {
    var timestamp: Date
    
    init(timestamp: Date) {
        self.timestamp = timestamp
    }
}
#else
final class Item {
    var timestamp: Date
    
    init(timestamp: Date) {
        self.timestamp = timestamp
    }
}
#endif
