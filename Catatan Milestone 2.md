Catatan Rencana Milestone HRD

SETUP RAG

supaya ga halu
    atur score kemiripan
    suruh AI untuk menulis proses apa saja yang dilakukan saat menjawab sebuah pertanyaan.

supaya irit token
    harus pakai top-k supaya konteks window ga meledak
tulis konteks bahasa inggris
    untuk data berupa pdf/doc chunking per halaman 

tanya faq/sop
minta buatin form cuti
    check avalability sop
    ada jatah cuti apa engga?
    yang diajuin sesuai sama jatah cuti apa engga?
    harus call rdbms untuk cek jatah cuti.

chunk nya udah disediakan tapi cek chunk nya udah bagus apa belum.

Parsing sebelum Chunking
    pada saat chunking, header dan footer hapus karena ga perlu.
    catat halaman dan bagian asal potongan

Chunking dan Metadata
    metadata diperlukan berupa ID document, ID Chunk, halaman
    versi dan hak ases diproses disini agar agent aware.

    Retrieval
Usahakan pakai String Match(Lexical) > Hybrid > Semantik(Dense) pada pencarian data vector
ketika user memberikan pertanyaan yang terdapat ID apapun, lakukan pencarian String Match, dan tanya lagi jika ga ketemu atau ketemu namun kode nya gak lengkap.

Chatbot harus bisa attach file untuk minta bukti cuti sakit (misalnya)
