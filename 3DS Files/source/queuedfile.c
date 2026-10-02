// queuedfile -- see queuedfile.h.

#include "queuedfile.h"

#include "bfile.h"
#include "joylog.h"

#define QF_HANDLE_MAX     100000
#define QF_BLOCK_SIZE     0x00100000
#define QF_PRIORITY       5
#define QF_STATUS_BITS    4
#define JOYLOG_CHANNEL_QUEUEDFILE_STATUS 5

BSlotPool *QueuedFileSlotPool;
int32_t QueuedFile_CurrentHandle = 1;
int32_t QueuedFileReadInProgress;
bNode QueuedFileList;

static void unlink_file(QueuedFile *qf)
{
    bNode *next = qf->Node.next;
    bNode *prev = qf->Node.prev;

    prev->next = next;
    next->prev = prev;
}

// ~QueuedFile (0x001adcb8) with the delete, QueuedFile::operator delete
// (0x001add38): the slot back to the pool.
static void delete_file(QueuedFile *qf)
{
    bSlotFree(QueuedFileSlotPool, qf);
}

// bStrCpy as far as the field holds, with nothing after the terminator.
static void copy_name(char *dst, size_t cap, const char *src)
{
    size_t i;

    for (i = 0; i + 1 < cap && src[i] != '\0'; i++)
        dst[i] = src[i];
    dst[i] = '\0';
}

// QueuedFile(void *, const char *, int, int, void (*)(int, int), int),
// 0x001ad6d8. The image's bStrCpy runs a name of 48 characters or more
// over FilePos and the rest; the port's copy stops at 47. The disc's names
// are far shorter.
static QueuedFile *construct(QueuedFile *qf, void *buf, const char *name,
                             int32_t pos, int32_t num_bytes,
                             QueuedFileCallback cb, intptr_t param)
{
    int32_t next;

    qf->pBuf = buf;
    qf->NumRead = 0;
    qf->FilePos = pos;
    qf->NumBytes = num_bytes;
    qf->BlockSize = QF_BLOCK_SIZE;
    qf->Priority = QF_PRIORITY;
    qf->Callback = cb;
    qf->CallbackParam = param;
    copy_name(qf->Filename, sizeof qf->Filename, name);
    qf->AbortFlag = 0;
    qf->Handle = QueuedFile_CurrentHandle;
    next = QueuedFile_CurrentHandle + 1;
    QueuedFile_CurrentHandle = next > QF_HANDLE_MAX ? 1 : next;
    qf->Status = QF_WAITING;
    return qf;
}

// ReadDoneCallback (0x001adc90).
static void read_done_callback(bFile *f, intptr_t param)
{
    (void)f;
    ((QueuedFile *)param)->Status = QF_DONE;
}

// SortByPriority (0x001adca0).
static int32_t sort_by_priority(bNode *a, bNode *b)
{
    return !(((QueuedFile *)b)->Priority < ((QueuedFile *)a)->Priority);
}

// BeginRead (0x001ad760).
static void begin_read(QueuedFile *qf)
{
    bFile  *f = bOpen(qf->Filename);
    int32_t n;

    if (f == NULL) {
        qf->Status = QF_ERROR;
        return;
    }
    n = qf->NumBytes - qf->NumRead;
    if (qf->BlockSize < n)
        n = qf->BlockSize;
    if (bFileSize(f) < qf->FilePos + qf->NumRead + n) {
        qf->Status = QF_ERROR;
    } else {
        qf->Status = QF_READING;
        bSeek(f, qf->FilePos + qf->NumRead, 0);
        bReadAsync(f, (uint8_t *)qf->pBuf + qf->NumRead, n,
                   read_done_callback, (intptr_t)qf);
        qf->NumRead += n;
    }
    bClose(f);
}

void queuedfile_static_init(void)
{
    QueuedFileList.prev = &QueuedFileList;
    QueuedFileList.next = &QueuedFileList;
}

void queuedfile_static_destruct(void)
{
    while (QueuedFileList.next != &QueuedFileList) {
        QueuedFile *qf = (QueuedFile *)QueuedFileList.next;

        unlink_file(qf);
        delete_file(qf);
    }
}

void init_queued_files(void)
{
    QueuedFileSlotPool = bNewSlotPool(100, 16, "QueuedFileSlotPool", 16);
}

void close_queued_files(void)
{
    if (QueuedFileSlotPool != NULL)
        bDeleteSlotPool(QueuedFileSlotPool);
}

int32_t add_queued_file(void *buf, const char *name, int32_t pos,
                        int32_t num_bytes, QueuedFileCallback cb,
                        intptr_t param)
{
    QueuedFile *qf = construct(bSlotOMalloc(QueuedFileSlotPool), buf, name,
                               pos, num_bytes, cb, param);
    bNode *last = QueuedFileList.prev;

    last->next = &qf->Node;
    QueuedFileList.prev = &qf->Node;
    qf->Node.prev = last;
    qf->Node.next = &QueuedFileList;
    return qf->Handle;
}

void change_queued_file_params(int32_t handle, int32_t priority,
                               int32_t block_size)
{
    QueuedFile *qf = find_queued_file(handle);

    if (qf != NULL) {
        qf->BlockSize = block_size;
        qf->Priority = priority;
    }
}

int32_t abort_queued_file(int32_t handle)
{
    QueuedFile *qf = find_queued_file(handle);

    if (qf == NULL)
        return 1;
    if (qf->Status == QF_WAITING) {
        unlink_file(qf);
        delete_file(qf);
        return 1;
    }
    qf->AbortFlag = 1;
    return 0;
}

QueuedFile *find_queued_file(int32_t handle)
{
    bNode *n;

    for (n = QueuedFileList.next; n != &QueuedFileList; n = n->next) {
        if (((QueuedFile *)n)->Handle == handle)
            return (QueuedFile *)n;
    }
    return NULL;
}

void service_queued_files(void)
{
    bServiceFileSystem();
    if (QueuedFileReadInProgress) {
        QueuedFile *qf = (QueuedFile *)QueuedFileList.next;
        int32_t status = qf->Status;

        if (Joylog_ReplayingFlag) {
            status = Joylog_GetData(QF_STATUS_BITS,
                                    JOYLOG_CHANNEL_QUEUEDFILE_STATUS);
            if (status != QF_READING && qf->Status == QF_READING) {
                do
                    bServiceFileSystem();
                while (qf->Status == QF_READING);
            }
        } else {
            Joylog_AddData(status, QF_STATUS_BITS,
                           JOYLOG_CHANNEL_QUEUEDFILE_STATUS);
        }

        if (status == QF_DONE) {
            QueuedFileReadInProgress = 0;
            qf->Status = QF_WAITING;
            if (qf->AbortFlag) {
                unlink_file(qf);
                delete_file(qf);
            } else if (qf->NumRead == qf->NumBytes) {
                unlink_file(qf);
                if (qf->Callback != NULL)
                    qf->Callback(qf->CallbackParam, 0);
                delete_file(qf);
            }
        } else if (status == QF_ERROR) {
            unlink_file(qf);
            QueuedFileReadInProgress = 0;
            if (qf->Callback != NULL)
                qf->Callback(qf->CallbackParam, 1);
            delete_file(qf);
        }
        if (QueuedFileReadInProgress)
            return;
    }
    if (QueuedFileList.next != &QueuedFileList) {
        blist_sort(&QueuedFileList, sort_by_priority);
        begin_read((QueuedFile *)QueuedFileList.next);
        QueuedFileReadInProgress = 1;
    }
}
