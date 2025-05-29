from fastapi import APIRouter

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"],
    responses={404: {"description": "Not found"}},
)

@router.get("/")
async def read_jobs():
    return {"message": "List of jobs"}

@router.post("/")
async def create_job():
    return {"message": "Job created"}


@router.get("/{job_id}")
async def read_job(job_id: int):
    return {"message": f"Details of job {job_id}"}

@router.delete("/{job_id}")
async def delete_job(job_id: int):
    return {"message": f"Job {job_id} deleted"}