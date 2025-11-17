from abstract_block_dumper.v1.decorators import block_task


@block_task(condition=lambda bn: True, celery_kwargs={"queue": "celery"})  # noqa: ARG005
def process_every_block(block_number: int) -> int:
    print(f"Processing every block: {block_number}")
    return block_number
