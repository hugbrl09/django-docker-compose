from django.db import models


class Documento(models.Model):
    titulo = models.CharField(max_length=200)
    arquivo = models.FileField(upload_to='documentos/')
    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-enviado_em']
        verbose_name = 'Documento'
        verbose_name_plural = 'Documentos'

    def __str__(self):
        return self.titulo
