import sys
from mastermind.graph import run_mastermind

def trigger_pipeline(account_key):
    print(f"🚀 BOOTING UP REAL PIPELINE FOR: {account_key}...")
    
    try:
        # Ye tera actual LangGraph mastermind run karega 
        # (Data Intelligence -> CMO -> Agent Executor)
        run_mastermind(account_key)
        
        print(f"\n✅ PIPELINE COMPLETED SUCCESSFULLY FOR {account_key}!")
    except Exception as e:
        print(f"\n❌ PIPELINE CRASHED: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # GitHub Action se account input lega, default 'account_1'
    target_account = sys.argv[1] if len(sys.argv) > 1 else "account_1"
    trigger_pipeline(target_account)
  
