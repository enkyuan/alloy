#!/usr/bin/env python3
"""Test script to verify Gemini API integration."""
import asyncio
import sys
import os

# Add app to path
sys.path.insert(0, os.path.dirname(__file__))

from app.services.gemini import get_gemini_service
from app.config import settings


async def test_gemini():
    """Test Gemini API integration."""
    print("=" * 60)
    print("Testing Gemini API Integration")
    print("=" * 60)
    
    # Check API key
    print(f"\n1. Checking GEMINI_API_KEY...")
    if not settings.GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY is not set!")
        print("   Set it in your .env file:")
        print("   GEMINI_API_KEY=your-api-key-here")
        return False
    
    print(f"✅ GEMINI_API_KEY is set (length: {len(settings.GEMINI_API_KEY)})")
    
    # Try to import google-genai
    print(f"\n2. Checking google-genai package...")
    try:
        from google import genai
        print("✅ google-genai package is installed")
    except ImportError as e:
        print(f"❌ google-genai package is not installed: {e}")
        print("   Install it with: poetry install")
        return False
    
    # Initialize service
    print(f"\n3. Initializing Gemini service...")
    try:
        gemini = get_gemini_service()
        print(f"✅ Gemini service initialized")
        print(f"   Model: {gemini.model}")
    except Exception as e:
        print(f"❌ Failed to initialize Gemini service: {e}")
        return False
    
    # Test simple generation
    print(f"\n4. Testing simple text generation...")
    try:
        response = await gemini.generate_response(
            prompt="Say hello in one sentence.",
            temperature=0.7
        )
        print(f"✅ Generation successful!")
        print(f"   Response: {response}")
    except Exception as e:
        print(f"❌ Generation failed: {e}")
        print(f"   Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test chat generation
    print(f"\n5. Testing chat generation...")
    try:
        messages = [
            {"role": "user", "content": "What is 2+2?"}
        ]
        response = await gemini.generate_chat_response(
            messages=messages,
            system_instruction="You are a helpful assistant. Keep responses brief.",
            temperature=0.7
        )
        print(f"✅ Chat generation successful!")
        print(f"   Response: {response}")
    except Exception as e:
        print(f"❌ Chat generation failed: {e}")
        print(f"   Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test streaming
    print(f"\n6. Testing streaming generation...")
    try:
        chunks = []
        async for chunk in gemini.generate_streaming_response(
            prompt="Count from 1 to 3.",
            temperature=0.7
        ):
            chunks.append(chunk)
            print(f"   Chunk: {chunk}")
        
        full_response = "".join(chunks)
        print(f"✅ Streaming successful!")
        print(f"   Full response: {full_response}")
    except Exception as e:
        print(f"❌ Streaming failed: {e}")
        print(f"   Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_gemini())
    sys.exit(0 if success else 1)
