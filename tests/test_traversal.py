import os

ARTIFACT_BASE = os.environ.get("ARTIFACT_BASE", "./artifacts")


def resolve(run_id, filename):
    base = os.path.realpath(ARTIFACT_BASE)
    path = os.path.realpath(os.path.join(base, run_id, filename))
    if path != base and not path.startswith(base + os.sep):
        return "BLOCKED (404)"
    return "SERVED: " + path


os.makedirs(os.path.join(ARTIFACT_BASE, "testrun"), exist_ok=True)
open(os.path.join(ARTIFACT_BASE, "testrun", "ok.txt"), "w").close()
print("legit  (testrun/ok.txt) ->", resolve("testrun", "ok.txt"))
print("attack (run_id='..', file='.env') ->", resolve("..", ".env"))
print("attack (run_id='..', file='..\\.env') ->", resolve("..", "..\\.env"))
os.remove(os.path.join(ARTIFACT_BASE, "testrun", "ok.txt"))
os.rmdir(os.path.join(ARTIFACT_BASE, "testrun"))
