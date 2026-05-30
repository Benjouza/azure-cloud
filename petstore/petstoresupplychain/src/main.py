"""
Entry point – Run the PetStore Supply Chain Orchestrator Agent locally as an interactive CLI.
"""

import sys
import traceback
from src.agent import create_orchestrator_agent, run_query, cleanup


def main():
    print("=" * 60)
    print("  PetStore Supply Chain Orchestrator Agent")
    print("  (type 'quit' or 'exit' to stop)")
    print("=" * 60)

    project_client, openai_client, agent, conversation = create_orchestrator_agent()

    intentional_exit = False
    try:
        while True:
            user_input = input("\n🔗 You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                intentional_exit = True
                break

            print("\n⏳ Processing...")
            try:
                response = run_query(openai_client, agent, conversation, user_input)
                print(f"\n🤖 Agent: {response}")
            except Exception as e:
                print(f"\n❌ Error processing query: {e}")
                traceback.print_exc()

    except KeyboardInterrupt:
        print("\n\nShutting down...")
        intentional_exit = True
    finally:
        if intentional_exit:
            cleanup(project_client, agent)
        print("Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
