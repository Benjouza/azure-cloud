"""
Entry point – Run the PetStore Supply Chain Orchestrator Agent locally as an interactive CLI.
"""

import sys
import traceback
from src.agent import create_orchestrator_client, run_query


def main():
    print("=" * 60)
    print("  PetStore Supply Chain Orchestrator Agent")
    print("  (type 'quit' or 'exit' to stop)")
    print("=" * 60)

    project_client, tools = create_orchestrator_client()

    try:
        while True:
            user_input = input("\n🔗 You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                break

            print("\n⏳ Processing...")
            try:
                response = run_query(project_client, tools, user_input)
                print(f"\n🤖 Agent: {response}")
            except Exception as e:
                print(f"\n❌ Error processing query: {e}")
                traceback.print_exc()

    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        print("Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
