import customtkinter as ctk

class VerticalRangeSlider(ctk.CTkFrame):
    """Simple two-handle vertical range slider built using two CTkSlider widgets."""

    def __init__(self, master, from_=0, to=1, number_of_steps=1, command=None, **kwargs):
        super().__init__(master, **kwargs)
        self._from = from_
        self._to = to
        self._command = command

        self._slider_low = ctk.CTkSlider(
            self,
            orientation="vertical",
            from_=from_,
            to=to,
            number_of_steps=number_of_steps,
            command=self._slider_moved,
            button_corner_radius=0,
        )
        self._slider_high = ctk.CTkSlider(
            self,
            orientation="vertical",
            from_=from_,
            to=to,
            number_of_steps=number_of_steps,
            command=self._slider_moved,
            button_corner_radius=0,
        )
        for sl in (self._slider_low, self._slider_high):
            sl.place(relx=0.5, rely=0, relheight=1, anchor="n")
            sl.configure(width=20)

        self.set(from_, to)

    def _slider_moved(self, _):
        if self._command:
            self._command(self.get())

    def get(self):
        v1 = self._slider_low.get()
        v2 = self._slider_high.get()
        return (min(v1, v2), max(v1, v2))

    def set(self, start, end):
        self._slider_low.set(start)
        self._slider_high.set(end)

    def configure(self, **kwargs):
        if "to" in kwargs:
            self._to = kwargs["to"]
            self._slider_low.configure(to=self._to)
            self._slider_high.configure(to=self._to)
        if "from_" in kwargs:
            self._from = kwargs["from_"]
            self._slider_low.configure(from_=self._from)
            self._slider_high.configure(from_=self._from)
        if "number_of_steps" in kwargs:
            steps = kwargs["number_of_steps"]
            self._slider_low.configure(number_of_steps=steps)
            self._slider_high.configure(number_of_steps=steps)
        super().configure(**{k:v for k,v in kwargs.items() if k not in {"to","from_","number_of_steps"}})
